param(
    [string]$Namespace = "vulnsentinel",
    [int]$BurstCount = 50,
    [int]$ScaleUpTarget = 2,
    [int]$ScaleDownTarget = 1,
    [int]$ScaleUpTimeoutSeconds = 300,
    [int]$ScaleDownTimeoutSeconds = 600,
    [string]$ImageRef = "",
    [string]$BaseImage = "nginx:latest",
    [switch]$SkipBurst,
    [switch]$SkipDatabaseCheck
)

$ErrorActionPreference = "Stop"
# In some PowerShell environments, native command stderr is promoted to terminating errors.
# Disable that behavior so transient kubectl warnings/timeouts don't abort validation loops.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$testScaleScript = Join-Path $scriptDir "test_scale.ps1"

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Check,
        [bool]$Passed,
        [string]$Details
    )

    $status = if ($Passed) { "PASS" } else { "FAIL" }
    $results.Add([pscustomobject]@{
            Check   = $Check
            Status  = $status
            Details = $Details
        })

    if ($Passed) {
        Write-Host "[PASS] $Check - $Details" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] $Check - $Details" -ForegroundColor Red
    }
}

function Get-ReplicaCount {
    param(
        [string]$NamespaceName,
        [string]$DeploymentName
    )

    try {
        $raw = kubectl -n $NamespaceName get deploy $DeploymentName -o jsonpath='{.status.replicas}' 2>$null
        if ($LASTEXITCODE -ne 0) {
            return -1
        }
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return 0
        }
        return [int]$raw
    }
    catch {
        return -1
    }
}

function Get-IntFromPsql {
    param(
        [string]$Sql
    )

    try {
        $raw = kubectl -n $Namespace exec deploy/postgres -- psql -U postgres -d vulnsentinel -t -A -c $Sql 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "psql query failed"
        }
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return 0
        }
        return [int]$raw.Trim()
    }
    catch {
        throw
    }
}

Write-Host "Validating VulnSentinel autoscaling in namespace '$Namespace'..." -ForegroundColor Cyan

$kubectlClient = kubectl version --client 2>$null
Add-Result "kubectl available" ($LASTEXITCODE -eq 0) "kubectl client detected"
if ($LASTEXITCODE -ne 0) {
    $results | Format-Table -AutoSize
    exit 1
}

$null = kubectl get namespace $Namespace 2>$null
$namespaceExists = $LASTEXITCODE -eq 0
Add-Result "Namespace exists" $namespaceExists "namespace=$Namespace"
if (-not $namespaceExists) {
    $results | Format-Table -AutoSize
    exit 1
}

$null = kubectl -n keda get deploy keda-operator 2>$null
$kedaReady = $LASTEXITCODE -eq 0
Add-Result "KEDA installed" $kedaReady "deployment=keda-operator"

$null = kubectl -n $Namespace get scaledobject worker-rabbitmq-scaler 2>$null
$scaledObjectExists = $LASTEXITCODE -eq 0
Add-Result "ScaledObject exists" $scaledObjectExists "scaledobject=worker-rabbitmq-scaler"

foreach ($dep in @("rabbitmq", "postgres", "rustfs", "worker")) {
    $ready = kubectl -n $Namespace get deploy $dep -o jsonpath='{.status.readyReplicas}' 2>$null
    if ([string]::IsNullOrWhiteSpace($ready)) {
        $ready = "0"
    }
    $ok = [int]$ready -ge 1
    Add-Result "Deployment ready: $dep" $ok "readyReplicas=$ready"
}

if (-not (Test-Path $testScaleScript)) {
    Add-Result "Burst script exists" $false "missing $testScaleScript"
    $results | Format-Table -AutoSize
    exit 1
}
Add-Result "Burst script exists" $true $testScaleScript

$preScans = 0
if (-not $SkipDatabaseCheck) {
    try {
        $preScans = Get-IntFromPsql "select count(*) from scans;"
        Add-Result "DB reachable" $true "pre_burst_scan_count=$preScans"
    }
    catch {
        Add-Result "DB reachable" $false "failed to query scans count"
    }
}

if (-not $SkipBurst) {
    Write-Host "Triggering burst test (count=$BurstCount)..." -ForegroundColor Cyan

    $invokeArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $testScaleScript,
        "-Count",
        [string]$BurstCount,
        "-Namespace",
        $Namespace,
        "-BaseImage",
        $BaseImage
    )
    if (-not [string]::IsNullOrWhiteSpace($ImageRef)) {
        $invokeArgs += @("-ImageRef", $ImageRef)
    }

    & powershell @invokeArgs
    $burstOk = $LASTEXITCODE -eq 0
    Add-Result "Burst job submitted" $burstOk "count=$BurstCount"
}
else {
    Add-Result "Burst job submitted" $true "skipped by flag"
}

Write-Host "Watching worker scale-up..." -ForegroundColor Cyan
$maxObservedReplicas = 0
$scaleUpAchieved = $false
$swUp = [System.Diagnostics.Stopwatch]::StartNew()

while ($swUp.Elapsed.TotalSeconds -lt $ScaleUpTimeoutSeconds) {
    $replicas = Get-ReplicaCount -NamespaceName $Namespace -DeploymentName "worker"
    if ($replicas -lt 0) {
        Start-Sleep -Seconds 5
        continue
    }
    if ($replicas -gt $maxObservedReplicas) {
        $maxObservedReplicas = $replicas
        Write-Host "Observed worker replicas: $replicas"
    }
    if ($replicas -ge $ScaleUpTarget) {
        $scaleUpAchieved = $true
        break
    }
    Start-Sleep -Seconds 5
}

Add-Result "Worker scales up" $scaleUpAchieved "max_observed=$maxObservedReplicas target>=$ScaleUpTarget"

Write-Host "Watching worker scale-down..." -ForegroundColor Cyan
$scaleDownAchieved = $false
$lastReplicas = Get-ReplicaCount -NamespaceName $Namespace -DeploymentName "worker"
$swDown = [System.Diagnostics.Stopwatch]::StartNew()

while ($swDown.Elapsed.TotalSeconds -lt $ScaleDownTimeoutSeconds) {
    $lastReplicas = Get-ReplicaCount -NamespaceName $Namespace -DeploymentName "worker"
    if ($lastReplicas -lt 0) {
        Start-Sleep -Seconds 10
        continue
    }
    if ($lastReplicas -le $ScaleDownTarget) {
        $scaleDownAchieved = $true
        break
    }
    Start-Sleep -Seconds 10
}

Add-Result "Worker scales down" $scaleDownAchieved "last_observed=$lastReplicas target<=$ScaleDownTarget"

if (-not $SkipDatabaseCheck) {
    try {
        $postScans = Get-IntFromPsql "select count(*) from scans;"
        $delta = $postScans - $preScans
        Add-Result "Scans persisted" ($delta -ge 1) "pre=$preScans post=$postScans delta=$delta"

        $recentFindings = Get-IntFromPsql "select count(*) from scan_results where created_at > now() - interval '30 minutes';"
        Add-Result "Findings persisted recently" ($recentFindings -ge 1) "recent_30m=$recentFindings"
    }
    catch {
        Add-Result "DB post-check" $false "failed to query post-burst database metrics"
    }
}
else {
    Add-Result "Database checks" $true "skipped by flag"
}

Write-Host ""
Write-Host "Validation summary:" -ForegroundColor Cyan
$results | Format-Table -AutoSize

$failed = @($results | Where-Object { $_.Status -eq "FAIL" })
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Autoscaling validation FAILED ($($failed.Count) failed checks)." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Autoscaling validation PASSED." -ForegroundColor Green
exit 0

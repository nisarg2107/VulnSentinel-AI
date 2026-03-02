param(
    [int]$Count = 50,
    [string]$Namespace = "vulnsentinel",
    [string]$ImageRef = "",
    [string]$BaseImage = "nginx:latest"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ImageRef)) {
    Write-Host "No --ImageRef provided. Resolving digest from local Docker image: $BaseImage"
    docker pull $BaseImage | Out-Null
    $resolvedRef = docker image inspect $BaseImage --format '{{index .RepoDigests 0}}'
    if ([string]::IsNullOrWhiteSpace($resolvedRef)) {
        throw "Failed to resolve image digest from docker image inspect for $BaseImage"
    }
    $ImageRef = $resolvedRef.Trim()
}

$jobName = "emitter-burst-{0}" -f ((Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss"))
$templatePath = Join-Path $PSScriptRoot "..\\k8s\\loadtest-burst-job.template.yaml"
$template = Get-Content $templatePath -Raw

$manifest = $template `
    -replace "__JOB_NAME__", $jobName `
    -replace "__NAMESPACE__", $Namespace `
    -replace "__BURST_COUNT__", [string]$Count `
    -replace "__IMAGE_REF__", $ImageRef

$manifest | kubectl apply -f -

Write-Host "Created burst job: $jobName"
Write-Host "Namespace: $Namespace"
Write-Host "Burst count: $Count"
Write-Host "Image ref: $ImageRef"
Write-Host "Watch worker scaling:"
Write-Host "  kubectl -n $Namespace get pods -w"
Write-Host "Watch queue depth (optional):"
Write-Host "  kubectl -n $Namespace port-forward svc/rabbitmq 15672:15672"

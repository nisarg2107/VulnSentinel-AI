# Grafana Frontend Blueprint For VulnSentinel AI

This dashboard is designed to prove value immediately: VulnSentinel filters vulnerability noise and prioritizes exploitable risks by combining SBOM + runtime context + VEX logic.

Database source-of-truth values remain OpenVEX-style (`affected`, `not_affected`, etc). Dashboard labels map these into user-facing terms (`open`, `suppressed`).

## Data Source

- Type: PostgreSQL
- Host: `host.docker.internal:5432` (Grafana in Docker)
- Database: `vulnsentinel`
- User/Password: local Postgres credentials

## UI Theme Modes

The dashboard supports Grafana UI theme modes:

- `System`
- `Light`
- `Dark`

Project default is `System` via compose env:

- `GF_USERS_DEFAULT_THEME=${GRAFANA_DEFAULT_THEME:-system}`

User-level override is available in Grafana profile preferences.

## Dashboard Variable (Image Drilldown)

Use a query variable named `image_name` with `Include All` enabled (`allValue='__all'`):

```sql
SELECT DISTINCT a.image_name
FROM assets a
JOIN scans s ON s.asset_id = a.id
WHERE s.status = 'completed'
ORDER BY 1;
```

This powers click-to-filter behavior across the vulnerability tables.

## Row 1: Risk Funnel & Value Metrics

### Panel 1: Total Images Scanned (Stat)

```sql
SELECT COUNT(DISTINCT asset_id) AS total_images_scanned
FROM scans
WHERE status = 'completed';
```

### Panel 2: Alert Fatigue Reduction (Stat / Bar Gauge)

Query A (Raw criticals):

```sql
SELECT COUNT(*) AS raw_criticals
FROM scan_results sr
JOIN scans s ON s.id = sr.scan_id
WHERE s.status = 'completed'
  AND sr.raw_severity = 'Critical';
```

Query B (Effective criticals still open/actionable):

```sql
SELECT COUNT(*) AS effective_criticals_open
FROM scan_results sr
JOIN scans s ON s.id = sr.scan_id
WHERE s.status = 'completed'
  AND sr.effective_severity = 'Critical'
  AND sr.status = 'affected';
```

### Panel 3: VEX Suppression Breakdown (Pie Chart)

```sql
SELECT
  CASE sr.status
    WHEN 'affected' THEN 'open'
    WHEN 'not_affected' THEN 'suppressed'
    ELSE sr.status
  END AS status,
  COUNT(*) AS total
FROM scan_results sr
JOIN scans s ON s.id = sr.scan_id
WHERE s.status = 'completed'
GROUP BY 1
ORDER BY total DESC;
```

## Row 2: Asset Inventory (Containers View)

### Panel 4: Asset Context Table (Table)

```sql
SELECT
  a.image_name AS "Image Name",
  SUBSTRING(a.image_digest, 1, 15) AS "Digest",
  ls.context->>'environment' AS "Environment",
  ls.context->>'is_exposed_public' AS "Is Exposed",
  ls.finished_at AS "Last Scanned"
FROM assets a
JOIN LATERAL (
  SELECT s.context, s.finished_at
  FROM scans s
  WHERE s.asset_id = a.id
    AND s.status = 'completed'
  ORDER BY s.finished_at DESC
  LIMIT 1
) ls ON true
ORDER BY ls.finished_at DESC;
```

Grafana mapping recommendation:
- Map `"Is Exposed"` values:
- `true` -> red warning style
- `false` -> green/gray style

## Row 3: Actionable Findings (Developer View)

### Panel 5: Actionable Risks Table (Table)

```sql
SELECT
  a.image_name AS "Affected Image",
  sr.vuln_id AS "Vulnerability",
  sr.package_name AS "Package",
  sr.package_version AS "Current Version",
  sr.fix_version AS "Available Fix",
  sr.effective_severity AS "Severity",
  'open' AS "Status",
  sr.cvss_score AS "CVSS"
FROM scan_results sr
JOIN scans s ON sr.scan_id = s.id
JOIN assets a ON s.asset_id = a.id
WHERE s.status = 'completed'
  AND sr.status = 'affected'
  AND ('${image_name}' = '__all' OR a.image_name = '${image_name}')
ORDER BY
  CASE sr.effective_severity
    WHEN 'Critical' THEN 1
    WHEN 'High' THEN 2
    WHEN 'Medium' THEN 3
    WHEN 'Low' THEN 4
    ELSE 5
  END,
  sr.cvss_score DESC NULLS LAST;
```

Grafana mapping recommendation:
- `"Severity"`:
- `Critical` -> dark red
- `High` -> orange
- `Medium` -> yellow
- `Low` -> green

## Row 4: Brain Audit Log (Security View)

### Panel 6: VEX Justification Log (Table)

```sql
SELECT
  a.image_name AS "Image",
  sr.vuln_id AS "Vulnerability",
  sr.raw_severity AS "Original Severity",
  sr.effective_severity AS "Effective Severity",
  'suppressed' AS "Status",
  sr.vex_justification AS "VEX Justification",
  s.finished_at AS "Scan Time"
FROM scan_results sr
JOIN scans s ON sr.scan_id = s.id
JOIN assets a ON s.asset_id = a.id
WHERE s.status = 'completed'
  AND sr.status = 'not_affected'
  AND ('${image_name}' = '__all' OR a.image_name = '${image_name}')
ORDER BY s.finished_at DESC;
```

## Row 5: Interactive Drilldown

### Panel 7: Open vs Suppressed by Image (Bar Chart)

```sql
SELECT
  a.image_name AS image,
  COUNT(*) FILTER (WHERE sr.status = 'affected') AS open,
  COUNT(*) FILTER (WHERE sr.status = 'not_affected') AS suppressed
FROM scan_results sr
JOIN scans s ON s.id = sr.scan_id
JOIN assets a ON a.id = s.asset_id
WHERE s.status = 'completed'
GROUP BY a.image_name
ORDER BY open DESC, suppressed DESC;
```

### Panel 8: Selected Image Vulnerability Details (Table)

```sql
SELECT
  a.image_name AS "Image",
  sr.vuln_id AS "Vulnerability",
  sr.package_name AS "Package",
  sr.package_version AS "Version",
  sr.raw_severity AS "Raw Severity",
  sr.effective_severity AS "Effective Severity",
  CASE
    WHEN sr.status = 'affected' THEN 'open'
    WHEN sr.status = 'not_affected' THEN 'suppressed'
    ELSE sr.status
  END AS "Status",
  sr.vex_justification AS "VEX Justification",
  sr.fix_version AS "Fix Version",
  sr.cvss_score AS "CVSS",
  s.finished_at AS "Scan Time"
FROM scan_results sr
JOIN scans s ON s.id = sr.scan_id
JOIN assets a ON a.id = s.asset_id
WHERE s.status = 'completed'
  AND ('${image_name}' = '__all' OR a.image_name = '${image_name}')
ORDER BY s.finished_at DESC, sr.cvss_score DESC NULLS LAST;
```

Add a data-link on panel 4 `"Image Name"` cells to update the variable:
- `/d/vulnsentinel-overview/vulnsentinel-risk-overview?var-image_name=${__value.raw}`

## Grafana Configuration Steps

1. Add PostgreSQL datasource in Grafana.
2. Set host `host.docker.internal:5432`, DB `vulnsentinel`, and local Postgres credentials.
3. Create panels (Stat/Pie/Table) and paste the queries above.
4. Apply Value Mappings and Overrides for exposure and severity color coding.
5. Column resize: in each table panel, hover between header boundaries and drag to resize columns.
6. Panel drag/reorder: open dashboard in **Edit mode** and drag panels by their header to reorder/swap positions.
7. Panel resize: in **Edit mode**, drag the panel corner/edge handles.

## Notes On Draggable Layout

- Dashboard JSON is set as `editable: true`.
- Provisioning is set with `allowUiUpdates: true`.
- You must be logged in with Editor/Admin rights to drag/reorder or resize panels.

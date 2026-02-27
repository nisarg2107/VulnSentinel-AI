# Grafana Dashboard UI Change Guide

This guide explains how to maintain two dashboard variants and apply color behavior changes without code risk.

## Goal

Support both views:

- Dashboard A: count-threshold coloring (volume/KPI style)
- Dashboard B: severity-based coloring (risk semantics style)

## Industry Approach (Recommended)

Most security teams use a hybrid model:

- Severity-based colors for severity fields (`Critical`, `High`, `Medium`, `Low`, `Unknown`)
- Threshold-based colors for KPI/SLO cards with explicit targets
- Neutral color when scope is `All severities` to avoid false "safe" signal

## Option 1: Create a Second Dashboard in UI (Fastest)

1. Open the existing dashboard in Grafana.
2. Click `Save` -> `Save as`.
3. Name it, for example: `VulnSentinel Risk Overview - Severity Colors`.
4. Edit this copied dashboard only.
5. Save.

This keeps the original dashboard unchanged.

## Option 2: Create a Second Provisioned Dashboard (Repo-backed)

Use this if changes should be versioned in Git.

1. Copy the JSON file:

```powershell
Copy-Item ".\\grafana\\dashboards\\vulnsentinel-overview.json" ".\\grafana\\dashboards\\vulnsentinel-overview-severity.json"
```

2. In the copied JSON, change:
- `title` to a new title
- `uid` to a new unique value
- `id` to `null` (or remove `id`)

3. Wait ~30 seconds for Grafana provisioning refresh, or restart Grafana:

```powershell
docker restart grafana
```

## Apply Severity-Based Colors (UI Steps)

For table panels with severity columns:

1. Panel title -> `Edit`
2. `Field` -> `Overrides` -> `Add override`
3. `Fields with name`: choose `Severity` (repeat for `Raw Severity` and `Effective Severity`)
4. Add property: `Value mappings`
5. Add values:

- `Critical` -> `#D44A3A` (red)
- `High` -> `#FF9830` (orange)
- `Medium` -> `#EAB839` (yellow)
- `Low` -> `#299C46` (green)
- `Unknown` -> `#808080` (gray)

6. Add property: `Cell display mode` -> `Color background`
7. `Apply` -> `Save dashboard`

## Notes for Stat Panels

Stat panels that return only numeric counts can only color by numeric thresholds.

If you want stat color to follow selected severity, the query must also return a severity/rank field (query-level change required).

## Quick Validation Checklist

After changes:

1. Set `Severity=Critical`: critical rows should be red-highlighted.
2. Set `Severity=High`: high rows should be orange-highlighted.
3. Set `Severity=All severities`: panel should stay neutral or use KPI thresholds only.
4. Check `Exposure=External/Internal`: data should still filter correctly.
5. Verify no panel remains empty due to stale browser cache; use hard refresh (`Ctrl+F5`).

## Rollback

UI-only rollback:

- Open dashboard version history and restore prior version.

Provisioned rollback:

- Revert the copied JSON file in Git and restart Grafana.

## File Paths in This Repo

- Provisioning config: `grafana/provisioning/dashboards/dashboards.yml`
- Dashboard files directory: `grafana/dashboards/`
- Grafana compose file: `docker-compose.grafana.yml`

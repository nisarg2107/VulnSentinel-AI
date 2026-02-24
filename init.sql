BEGIN;

CREATE TABLE IF NOT EXISTS assets (
    id BIGSERIAL PRIMARY KEY,
    image_digest TEXT NOT NULL UNIQUE,
    image_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scanned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT assets_image_digest_sha256_chk
        CHECK (image_digest ~ '^sha256:[0-9a-fA-F]{64}$')
);

CREATE TABLE IF NOT EXISTS scans (
    id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    job_id UUID UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error TEXT NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    tool_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    sbom_object_key TEXT NULL,
    sbom_sha256 TEXT NULL,
    sbom_bytes BIGINT NULL,
    report_object_key TEXT NULL,
    report_sha256 TEXT NULL,
    report_bytes BIGINT NULL,
    CONSTRAINT scans_status_chk
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT scans_finished_after_started_chk
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT scans_sbom_sha256_chk
        CHECK (sbom_sha256 IS NULL OR sbom_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CONSTRAINT scans_report_sha256_chk
        CHECK (report_sha256 IS NULL OR report_sha256 ~ '^[0-9a-fA-F]{64}$'),
    CONSTRAINT scans_sbom_bytes_nonneg_chk
        CHECK (sbom_bytes IS NULL OR sbom_bytes >= 0),
    CONSTRAINT scans_report_bytes_nonneg_chk
        CHECK (report_bytes IS NULL OR report_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS scan_results (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    vuln_id TEXT NOT NULL,
    package_name TEXT NOT NULL,
    package_version TEXT NULL,
    package_type TEXT NULL,
    package_path TEXT NULL,
    raw_severity TEXT NOT NULL,
    effective_severity TEXT NOT NULL,
    status TEXT NOT NULL,
    vex_justification TEXT NULL,
    fix_version TEXT NULL,
    cvss_score NUMERIC(4,1) NULL,
    raw_finding JSONB NOT NULL DEFAULT '{}'::jsonb,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scan_results_raw_severity_chk
        CHECK (raw_severity IN ('Unknown', 'Negligible', 'Low', 'Medium', 'High', 'Critical')),
    CONSTRAINT scan_results_effective_severity_chk
        CHECK (effective_severity IN ('Unknown', 'Negligible', 'Low', 'Medium', 'High', 'Critical')),
    CONSTRAINT scan_results_status_chk
        CHECK (status IN ('not_affected', 'affected', 'fixed', 'under_investigation')),
    CONSTRAINT scan_results_vex_justification_chk
        CHECK (
            vex_justification IS NULL OR vex_justification IN (
                'component_not_present',
                'vulnerable_code_not_present',
                'vulnerable_code_not_in_execute_path',
                'vulnerable_code_cannot_be_controlled_by_adversary',
                'inline_mitigations_already_exist'
            )
        ),
    CONSTRAINT scan_results_vex_required_when_not_affected_chk
        CHECK (status <> 'not_affected' OR vex_justification IS NOT NULL),
    CONSTRAINT scan_results_cvss_score_range_chk
        CHECK (cvss_score IS NULL OR (cvss_score >= 0 AND cvss_score <= 10))
);

CREATE UNIQUE INDEX IF NOT EXISTS scan_results_dedupe_idx
    ON scan_results (
        scan_id,
        vuln_id,
        package_name,
        COALESCE(package_version, ''),
        COALESCE(package_type, ''),
        COALESCE(package_path, '')
    );

CREATE INDEX IF NOT EXISTS scans_asset_id_idx ON scans (asset_id);
CREATE INDEX IF NOT EXISTS scans_status_idx ON scans (status);
CREATE INDEX IF NOT EXISTS scans_created_at_idx ON scans (created_at DESC);
CREATE INDEX IF NOT EXISTS scan_results_scan_id_idx ON scan_results (scan_id);
CREATE INDEX IF NOT EXISTS scan_results_vuln_id_idx ON scan_results (vuln_id);
CREATE INDEX IF NOT EXISTS scan_results_effective_severity_idx ON scan_results (effective_severity);

CREATE OR REPLACE FUNCTION set_asset_last_scanned_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'completed' THEN
        UPDATE assets
        SET last_scanned_at = COALESCE(NEW.finished_at, now())
        WHERE id = NEW.asset_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS scans_set_asset_last_scanned_at ON scans;
CREATE TRIGGER scans_set_asset_last_scanned_at
AFTER INSERT OR UPDATE OF status, finished_at ON scans
FOR EACH ROW
WHEN (NEW.status = 'completed')
EXECUTE FUNCTION set_asset_last_scanned_at();

COMMIT;

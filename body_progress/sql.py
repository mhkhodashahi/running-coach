"""Portable SQL snippets for app adapters that do not use migrations yet."""

BODY_SCANS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS body_scans (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    scan_date DATE NOT NULL,
    view VARCHAR(32) NOT NULL DEFAULT 'front',
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    source_image_path TEXT,
    preview_image_path TEXT,
    mesh_path TEXT,
    keypoints_json TEXT,
    measurements_json TEXT,
    pose_quality FLOAT,
    processor_name VARCHAR(64),
    error_message TEXT,
    consent_to_store_image BOOLEAN NOT NULL DEFAULT 1,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users (id)
)
"""

BODY_SCANS_INDEX_SQL = "CREATE INDEX IF NOT EXISTS ix_body_scans_user_id ON body_scans (user_id)"
BODY_SCANS_DATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS ix_body_scans_scan_date ON body_scans (scan_date)"

BODY_SCAN_INSIGHTS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS body_scan_insights (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    insight_date DATE NOT NULL,
    scan_ids_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prompt_context_json TEXT NOT NULL,
    model_provider VARCHAR(32),
    model_name VARCHAR(80),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users (id)
)
"""

BODY_SCAN_INSIGHTS_USER_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_body_scan_insights_user_id ON body_scan_insights (user_id)"
)
BODY_SCAN_INSIGHTS_DATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_body_scan_insights_insight_date ON body_scan_insights (insight_date)"
)

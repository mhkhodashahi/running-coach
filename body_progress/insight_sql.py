"""SQL snippets for body scan LLM insight history."""

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

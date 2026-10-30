CREATE TABLE users (
	id INTEGER NOT NULL, 
	age INTEGER, 
	gender VARCHAR(20), 
	weight FLOAT, 
	height FLOAT, 
	max_hr INTEGER, 
	marathon_goal_time VARCHAR(16) NOT NULL, 
	marathon_date DATE, name VARCHAR(80), training_days_per_week INTEGER, injury_notes TEXT, running_goal_time VARCHAR(16) NOT NULL DEFAULT '03:59:59', running_date DATE, 
	PRIMARY KEY (id)
);
CREATE TABLE activities (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	external_id VARCHAR(64), 
	date DATE NOT NULL, 
	type VARCHAR(32) NOT NULL, 
	distance FLOAT NOT NULL, 
	duration FLOAT NOT NULL, 
	pace FLOAT, 
	avg_hr FLOAT, 
	max_hr FLOAT, 
	cadence FLOAT, 
	elevation FLOAT, 
	training_effect FLOAT, 
	aerobic_effect FLOAT, 
	anaerobic_effect FLOAT, 
	notes TEXT, activity_name VARCHAR(160), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activities_user_external UNIQUE (user_id, external_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_activities_date ON activities (date);
CREATE INDEX ix_activities_user_id ON activities (user_id);
CREATE TABLE health_metrics (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	sleep_duration FLOAT, 
	sleep_score FLOAT, 
	resting_hr FLOAT, 
	hrv FLOAT, 
	stress FLOAT, 
	body_battery FLOAT, 
	recovery_time FLOAT, 
	vo2max FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_health_metrics_user_date UNIQUE (user_id, date), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_health_metrics_user_id ON health_metrics (user_id);
CREATE INDEX ix_health_metrics_date ON health_metrics (date);
CREATE TABLE llm_memory (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	date DATETIME NOT NULL, 
	context_summary TEXT NOT NULL, 
	recommendations TEXT NOT NULL, 
	fatigue_flag BOOLEAN NOT NULL, 
	confidence_score FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_llm_memory_user_id ON llm_memory (user_id);
CREATE TABLE goals (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	goal_type VARCHAR(32) NOT NULL, 
	target_distance_km FLOAT NOT NULL, 
	target_time_minutes FLOAT NOT NULL, 
	target_date DATE, 
	priority VARCHAR(8) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_goals_user_id ON goals (user_id);
CREATE TABLE coaching_decisions (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	goal_id INTEGER, 
	decision_type VARCHAR(16) NOT NULL, 
	decision_date DATE NOT NULL, 
	summary TEXT NOT NULL, 
	risk_level VARCHAR(16) NOT NULL, 
	payload_json TEXT NOT NULL, 
	email_subject TEXT, 
	email_body TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(goal_id) REFERENCES goals (id)
);
CREATE INDEX ix_coaching_decisions_user_id ON coaching_decisions (user_id);
CREATE INDEX ix_coaching_decisions_decision_date ON coaching_decisions (decision_date);
CREATE INDEX ix_coaching_decisions_goal_id ON coaching_decisions (goal_id);
CREATE TABLE email_deliveries (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	coaching_decision_id INTEGER, 
	recipient VARCHAR(255) NOT NULL, 
	subject TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	provider_message TEXT, 
	sent_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(coaching_decision_id) REFERENCES coaching_decisions (id)
);
CREATE INDEX ix_email_deliveries_user_id ON email_deliveries (user_id);
CREATE INDEX ix_email_deliveries_coaching_decision_id ON email_deliveries (coaching_decision_id);
CREATE TABLE activity_track_points (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	point_index INTEGER NOT NULL, 
	timestamp DATETIME, 
	elapsed_seconds FLOAT, 
	distance_km FLOAT, 
	latitude FLOAT, 
	longitude FLOAT, 
	elevation FLOAT, 
	pace FLOAT, 
	speed FLOAT, 
	heart_rate FLOAT, 
	cadence FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_track_points_index UNIQUE (activity_id, point_index), 
	FOREIGN KEY(activity_id) REFERENCES activities (id)
);
CREATE INDEX ix_activity_track_points_activity_id ON activity_track_points (activity_id);
CREATE TABLE activity_laps (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	lap_index INTEGER NOT NULL, 
	lap_type VARCHAR(32), 
	start_time DATETIME, 
	duration FLOAT, 
	distance FLOAT, 
	pace FLOAT, 
	avg_hr FLOAT, 
	max_hr FLOAT, 
	elevation_gain FLOAT, 
	avg_cadence FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_laps_index UNIQUE (activity_id, lap_index), 
	FOREIGN KEY(activity_id) REFERENCES activities (id)
);
CREATE INDEX ix_activity_laps_activity_id ON activity_laps (activity_id);
CREATE TABLE body_scans (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	scan_date DATE NOT NULL, 
	"view" VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	source_image_path TEXT, 
	preview_image_path TEXT, 
	mesh_path TEXT, 
	keypoints_json TEXT, 
	measurements_json TEXT, 
	pose_quality FLOAT, 
	processor_name VARCHAR(64), 
	error_message TEXT, 
	consent_to_store_image BOOLEAN NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_body_scans_user_id ON body_scans (user_id);
CREATE INDEX ix_body_scans_scan_date ON body_scans (scan_date);
CREATE TABLE body_scan_insights (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	insight_date DATE NOT NULL, 
	scan_ids_json TEXT NOT NULL, 
	summary TEXT NOT NULL, 
	payload_json TEXT NOT NULL, 
	prompt_context_json TEXT NOT NULL, 
	model_provider VARCHAR(32), 
	model_name VARCHAR(80), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_body_scan_insights_insight_date ON body_scan_insights (insight_date);
CREATE INDEX ix_body_scan_insights_user_id ON body_scan_insights (user_id);
CREATE TABLE nutrition_entries (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	entry_date DATE NOT NULL, 
	meal_type VARCHAR(32) NOT NULL, 
	food_name VARCHAR(120) NOT NULL, 
	calories FLOAT NOT NULL, 
	protein_g FLOAT NOT NULL, 
	carbs_g FLOAT NOT NULL, 
	fat_g FLOAT NOT NULL, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);
CREATE INDEX ix_nutrition_entries_user_id ON nutrition_entries (user_id);
CREATE INDEX ix_nutrition_entries_entry_date ON nutrition_entries (entry_date);
CREATE TABLE activity_coaching_insights (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	summary TEXT NOT NULL, 
	payload_json TEXT NOT NULL, 
	prompt_context_json TEXT NOT NULL, 
	model_provider VARCHAR(32), 
	model_name VARCHAR(80), 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_coaching_insights_activity UNIQUE (activity_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(activity_id) REFERENCES activities (id)
);
CREATE INDEX ix_activity_coaching_insights_activity_id ON activity_coaching_insights (activity_id);
CREATE INDEX ix_activity_coaching_insights_user_id ON activity_coaching_insights (user_id);
CREATE TABLE prediction_snapshots (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	activity_id INTEGER, 
	goal_id INTEGER, 
	prediction_date DATE NOT NULL, 
	race_distance_km FLOAT NOT NULL, 
	predicted_time_minutes FLOAT NOT NULL, 
	predicted_pace FLOAT NOT NULL, 
	gap_minutes FLOAT NOT NULL, 
	confidence FLOAT NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_prediction_snapshots_activity_goal UNIQUE (activity_id, goal_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(activity_id) REFERENCES activities (id), 
	FOREIGN KEY(goal_id) REFERENCES goals (id)
);
CREATE INDEX ix_prediction_snapshots_goal_id ON prediction_snapshots (goal_id);
CREATE INDEX ix_prediction_snapshots_user_id ON prediction_snapshots (user_id);
CREATE INDEX ix_prediction_snapshots_activity_id ON prediction_snapshots (activity_id);
CREATE INDEX ix_prediction_snapshots_prediction_date ON prediction_snapshots (prediction_date);
CREATE TABLE garmin_sync_status (
	user_id INTEGER NOT NULL, 
	last_synced_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

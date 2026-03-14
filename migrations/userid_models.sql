ALTER TABLE models ADD COLUMN user_id UUID REFERENCES users(user_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_models_user ON models(user_id);
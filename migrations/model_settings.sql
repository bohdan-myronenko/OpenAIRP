-- Add model settings overrides to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_model_id INTEGER REFERENCES models(model_id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_temperature FLOAT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_max_tokens INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_top_p FLOAT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_frequency_penalty FLOAT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_presence_penalty FLOAT;

-- Add model settings overrides to chats
ALTER TABLE chats ADD COLUMN IF NOT EXISTS model_id INTEGER REFERENCES models(model_id) ON DELETE SET NULL;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS temperature FLOAT;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS max_tokens INTEGER;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS top_p FLOAT;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS frequency_penalty FLOAT;
ALTER TABLE chats ADD COLUMN IF NOT EXISTS presence_penalty FLOAT;

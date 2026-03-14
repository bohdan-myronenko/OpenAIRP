-- Initial database schema
-- This script only runs when the database is first created (empty data directory)
-- It uses IF NOT EXISTS to be idempotent and safe if run multiple times
-- All migrations have been consolidated into this single init file

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table with UUID primary key and admin support
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_admin BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_admin ON users(is_admin);

-- Tags table
CREATE TABLE IF NOT EXISTS tags (
    tag_id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL
);

-- Bots table with UUID creator_id
CREATE TABLE IF NOT EXISTS bots (
    bot_id SERIAL PRIMARY KEY,
    creator_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    avatar_url TEXT,
    title VARCHAR(100) NOT NULL,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    is_nsfw BOOLEAN DEFAULT false,
    persona TEXT NOT NULL,
    scenario TEXT,
    greeting TEXT,
    example_dialog TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bots_creator ON bots(creator_id);

-- Bot tags junction table
CREATE TABLE IF NOT EXISTS bot_tags (
    bot_id INTEGER REFERENCES bots(bot_id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (bot_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_tags_tag ON bot_tags(tag_id);

-- Personas table with UUID user_id
CREATE TABLE IF NOT EXISTS personas (
    persona_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    avatar_url TEXT,
    name VARCHAR(50) NOT NULL,
    description TEXT,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personas_user ON personas(user_id);

-- Chats table with VARCHAR(22) chat_id and UUID user_id
CREATE TABLE IF NOT EXISTS chats (
    chat_id VARCHAR(22) PRIMARY KEY,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    bot_id INTEGER REFERENCES bots(bot_id) ON DELETE CASCADE,
    persona_id INTEGER REFERENCES personas(persona_id) ON DELETE SET NULL,
    memory TEXT,
    title VARCHAR(100),
    last_used TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, last_used);

-- Messages table with VARCHAR(22) chat_id and reroll support
CREATE TABLE IF NOT EXISTS messages (
    message_id SERIAL PRIMARY KEY,
    chat_id VARCHAR(22) REFERENCES chats(chat_id) ON DELETE CASCADE,
    sender_type VARCHAR(5) CHECK (sender_type IN ('user', 'bot')) NOT NULL,
    content TEXT NOT NULL,
    parent_message_id INTEGER REFERENCES messages(message_id) ON DELETE CASCADE,
    attempt_number INTEGER DEFAULT 0,
    is_selected BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_message_id, attempt_number);

-- System prompts table
CREATE TABLE IF NOT EXISTS system_prompts (
    prompt_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_system_prompts_active ON system_prompts(is_active);

-- Models table
CREATE TABLE IF NOT EXISTS models (
    model_id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    api_url TEXT NOT NULL,
    api_key TEXT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    custom_prompt TEXT,
    is_active BOOLEAN DEFAULT false,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_models_active ON models(is_active);
CREATE INDEX IF NOT EXISTS idx_models_user ON models(user_id);

-- Sessions table for cookie-based authentication
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

# services/api/app/main.py

import logging
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncpg
import os

from app.db import connect, disconnect
from routers import health, bots, chats, system_prompts, models, personas, users

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Open Roleplay API",
    version="0.1.0",
    description="HTTP API for bots, chats, and admin tooling.",
)

allowed_origins = os.getenv("CORS_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins if o.strip()] or ["http://localhost"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.on_event("startup")
async def on_startup():
    try:
        await connect()
        logger.info("Database connection pool created successfully")
        
        # Ensure required tables exist (fallback if migration hasn't run)
        try:
            from app.db import _pool
            pool = _pool
            logger.info(f"Pool status: {pool is not None}")
            
            if pool:
                async with pool.acquire() as conn:
                    # Create models table
                    await conn.execute("""
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
                        )
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_models_active ON models(is_active)
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_models_user ON models(user_id)
                    """)
                    # Add user_id column if it doesn't exist (for existing databases)
                    # Check if column exists first
                    column_exists = await conn.fetchval("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.columns 
                            WHERE table_schema = 'public' 
                            AND table_name = 'models' 
                            AND column_name = 'user_id'
                        )
                    """)
                    
                    if not column_exists:
                        try:
                            # Add the column
                            await conn.execute("""
                                ALTER TABLE models 
                                ADD COLUMN user_id UUID REFERENCES users(user_id) ON DELETE CASCADE
                            """)
                            logger.info("Added user_id column to models table")
                        except Exception as e:
                            logger.warning(f"Could not add user_id column (might already exist): {e}")
                    
                    # Ensure index exists
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_models_user ON models(user_id)
                    """)
                    
                    # Create system_prompts table
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS system_prompts (
                            prompt_id SERIAL PRIMARY KEY,
                            name VARCHAR(100) NOT NULL,
                            content TEXT NOT NULL,
                            is_active BOOLEAN DEFAULT true,
                            description TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    await conn.execute("""
                        CREATE INDEX IF NOT EXISTS idx_system_prompts_active ON system_prompts(is_active)
                    """)
                    
                    # Add reroll attempt columns if they don't exist (migration fallback)
                    try:
                        # Check if columns exist first
                        existing_cols = await conn.fetch("""
                            SELECT column_name FROM information_schema.columns 
                            WHERE table_name = 'messages' AND column_name IN ('parent_message_id', 'attempt_number', 'is_selected')
                        """)
                        existing_col_names = [r["column_name"] for r in existing_cols]
                        
                        if "parent_message_id" not in existing_col_names:
                            await conn.execute("""
                                ALTER TABLE messages ADD COLUMN parent_message_id INTEGER REFERENCES messages(message_id) ON DELETE CASCADE
                            """)
                        
                        if "attempt_number" not in existing_col_names:
                            await conn.execute("""
                                ALTER TABLE messages ADD COLUMN attempt_number INTEGER DEFAULT 0
                            """)
                        
                        if "is_selected" not in existing_col_names:
                            await conn.execute("""
                                ALTER TABLE messages ADD COLUMN is_selected BOOLEAN DEFAULT true
                            """)
                        
                        await conn.execute("""
                            CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_message_id, attempt_number)
                        """)
                        await conn.execute("""
                            UPDATE messages SET attempt_number = 0, is_selected = true WHERE attempt_number IS NULL OR is_selected IS NULL
                        """)
                        
                        logger.info("Reroll attempt columns verified/created")
                    except asyncpg.exceptions.UndefinedTableError:
                        # Messages table doesn't exist yet, skip
                        pass
                    except Exception as e:
                        logger.warning(f"Could not add reroll columns: {e}")
                        # Don't re-raise - let startup continue
                    
                    # Create sessions table for cookie-based authentication
                    # This is critical for login functionality - must exist for auth to work
                    try:
                        # Check if sessions table already exists
                        sessions_exists = await conn.fetchval("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = 'sessions'
                            )
                        """)
                        
                        if not sessions_exists:
                            # Verify users table exists first (required for foreign key)
                            users_exists = await conn.fetchval("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables 
                                    WHERE table_schema = 'public' 
                                    AND table_name = 'users'
                                )
                            """)
                            
                            if not users_exists:
                                logger.warning("Users table does not exist yet. Skipping sessions table creation.")
                            else:
                                # Create sessions table - use same definition as init.sql
                                await conn.execute("""
                                    CREATE TABLE IF NOT EXISTS sessions (
                                        session_id VARCHAR(255) PRIMARY KEY,
                                        user_id UUID REFERENCES users(user_id) ON DELETE CASCADE NOT NULL,
                                        expires_at TIMESTAMP NOT NULL,
                                        created_at TIMESTAMP DEFAULT NOW()
                                    )
                                """)
                                await conn.execute("""
                                    CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)
                                """)
                                await conn.execute("""
                                    CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)
                                """)
                                logger.info("Sessions table created successfully during startup")
                        else:
                            logger.debug("Sessions table already exists")
                    except asyncpg.exceptions.UndefinedTableError as e:
                        logger.error(f"CRITICAL: Cannot create sessions table - users table issue: {e}", exc_info=True)
                        # Don't fail startup, but log as critical
                    except asyncpg.exceptions.DuplicateTableError:
                        logger.info("Sessions table already exists (duplicate check)")
                    except Exception as e:
                        logger.error(f"CRITICAL: Failed to create sessions table: {e}", exc_info=True)
                        # Log as critical but don't fail startup - table might exist from init.sql
                    
                    logger.info("Required tables verified/created")
            else:
                logger.warning("Database pool not available during startup - columns may not be created")
        except Exception as e:
            logger.warning(f"Could not verify/create tables: {e}", exc_info=True)
            # Don't fail startup if table creation fails - migration might handle it
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def on_shutdown():
    await disconnect()
    logger.info("Database connection pool closed")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to catch all unhandled exceptions."""
    logger.error(
        f"Unhandled exception: {exc}",
        exc_info=True,
        extra={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": f"Internal server error: {str(exc)}",
            "type": type(exc).__name__,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors."""
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(asyncpg.PostgresError)
async def postgres_exception_handler(request: Request, exc: asyncpg.PostgresError):
    """Handle PostgreSQL-specific errors."""
    logger.error(f"PostgreSQL error: {exc} (path: {request.url.path})", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": f"Database error: {str(exc)}",
            "type": type(exc).__name__,
        },
    )


# Routers
app.include_router(health.router)
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(bots.router, prefix="/bots", tags=["bots"])
app.include_router(chats.router, prefix="/chats", tags=["chats"])
app.include_router(system_prompts.router, prefix="/system-prompts", tags=["system-prompts"])
app.include_router(models.router, prefix="/models", tags=["models"])
app.include_router(personas.router, prefix="/personas", tags=["personas"])

# Note: Static files (uploads) are now served by the warehouse-server container
# Files are still written to /app/warehouse/uploads in this container (shared volume)
# but served via the warehouse-server service for better cross-device access
uploads_dir = Path("/app/warehouse/uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)


@app.get("/")
async def root():
    return {"status": "ok", "service": "api"}

# services/api/app/db.py

import os
import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)
_pool: Optional[asyncpg.Pool] = None

# Export _pool for startup checks (models table creation)
__all__ = ["connect", "disconnect", "get_pool", "_pool"]


def _build_database_url() -> str:
    # Highest priority: full DATABASE_URL
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Otherwise, build from individual components (matches your docker-compose/db service)
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    host = os.getenv("DB_HOST", "db")  # docker service name
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "postgres")

    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


async def connect() -> None:
    """Create a global asyncpg connection pool."""
    global _pool
    if _pool is not None:
        return

    database_url = _build_database_url()
    # Don't log the full URL (contains password), just the host
    logger.info(f"Connecting to database at {os.getenv('DB_HOST', 'db')}:{os.getenv('DB_PORT', '5432')}")
    try:
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
        logger.info("Database connection pool created successfully")
    except Exception as e:
        logger.error(f"Failed to create database connection pool: {e}", exc_info=True)
        raise


async def disconnect() -> None:
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """FastAPI dependency to get the connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialised")
    return _pool


def get_pool_sync() -> Optional[asyncpg.Pool]:
    """Get the pool synchronously (for startup checks). Returns None if not initialized."""
    return _pool
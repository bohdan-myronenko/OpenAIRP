# services/api/app/auth.py

import os
import logging
import secrets
import base64
from datetime import datetime, timedelta
from uuid import UUID, uuid5, NAMESPACE_DNS

from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.security.utils import get_authorization_scheme_param
from typing import Optional
import asyncpg
import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from app.db import get_pool

logger = logging.getLogger(__name__)
security = HTTPBasic()

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = secrets.token_urlsafe(32)  # Generate secret if not set
    logger.warning(
        "JWT_SECRET_KEY not set in environment. Using generated key. "
        "This will invalidate tokens on server restart. Set JWT_SECRET_KEY in .env for production."
    )
JWT_ALGORITHM = "HS256"
JWT_COOKIE_NAME = "access_token"
JWT_ACCESS_TOKEN_EXPIRE_DAYS = 30  # For "remember me"
JWT_ACCESS_TOKEN_EXPIRE_HOURS = 24  # For session cookies (when remember_me=False)


async def get_optional_credentials(request: Request) -> Optional[HTTPBasicCredentials]:
    """Get HTTP Basic Auth credentials if present, otherwise return None."""
    authorization = request.headers.get("Authorization")
    if not authorization:
        return None
    
    scheme, credentials = get_authorization_scheme_param(authorization)
    if scheme.lower() != "basic":
        return None
    
    try:
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, _, password = decoded.partition(":")
        return HTTPBasicCredentials(username=username, password=password)
    except Exception:
        return None

# Legacy session configuration (for backward compatibility)
SESSION_COOKIE_NAME = "session_token"
SESSION_DURATION_DAYS = 30  # Sessions expire after 30 days

# Admin credentials from environment
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def create_jwt_token(user_id: str, username: str, email: str, is_admin: bool, remember_me: bool = False) -> tuple[str, int]:
    """
    Create a JWT token for a user.
    Returns (token, max_age_in_seconds).
    If remember_me is False, token expires in JWT_ACCESS_TOKEN_EXPIRE_HOURS (session cookie).
    If remember_me is True, token expires in JWT_ACCESS_TOKEN_EXPIRE_DAYS.
    """
    if remember_me:
        expires_delta = timedelta(days=JWT_ACCESS_TOKEN_EXPIRE_DAYS)
        max_age = JWT_ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60  # Days to seconds
    else:
        expires_delta = timedelta(hours=JWT_ACCESS_TOKEN_EXPIRE_HOURS)
        max_age = JWT_ACCESS_TOKEN_EXPIRE_HOURS * 60 * 60  # Hours to seconds
    
    expire = datetime.utcnow() + expires_delta
    
    payload = {
        "sub": str(user_id),  # Subject (user ID)
        "username": username,
        "email": email,
        "is_admin": is_admin,
        "exp": expire,  # Expiration time
        "iat": datetime.utcnow(),  # Issued at
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, max_age


def verify_jwt_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token.
    Returns user info dict if valid, None otherwise.
    """
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
            "email": payload.get("email"),
            "is_admin": payload.get("is_admin", False),
        }
    except ExpiredSignatureError:
        logger.debug("JWT token expired")
        return None
    except InvalidTokenError as e:
        logger.debug(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error verifying JWT token: {e}")
        return None


async def create_session(user_id: UUID, pool: asyncpg.Pool, remember_me: bool = False) -> tuple[str, int]:
    """
    Create a new session for a user and return the session token and max_age in seconds.
    If remember_me is False, session expires when browser closes (max_age=None).
    If remember_me is True, session expires after SESSION_DURATION_DAYS.
    """
    session_token = secrets.token_urlsafe(32)  # Generate secure random token
    
    if remember_me:
        expires_at = datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)
        max_age = SESSION_DURATION_DAYS * 24 * 60 * 60  # 30 days in seconds
    else:
        # Session cookie (expires when browser closes) - set expiration to 1 day for safety
        expires_at = datetime.utcnow() + timedelta(days=1)
        max_age = None  # Session cookie (expires when browser closes)
    
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (session_id, user_id, expires_at)
            VALUES ($1, $2, $3)
            """,
            session_token,
            user_id,
            expires_at,
        )
    
    return session_token, max_age


async def get_session(session_token: str, pool: asyncpg.Pool) -> Optional[dict]:
    """Get session information if valid, otherwise return None."""
    if not session_token:
        return None
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.user_id, s.expires_at, u.username, u.email, COALESCE(u.is_admin, false) as is_admin
            FROM sessions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.session_id = $1 AND s.expires_at > NOW()
            """,
            session_token,
        )
        
        if not row:
            return None
        
        # Convert UUID to string for JSON serialization
        user_id = row["user_id"]
        if isinstance(user_id, UUID):
            user_id = str(user_id)
        
        return {
            "user_id": user_id,
            "username": row["username"],
            "email": row["email"],
            "is_admin": row["is_admin"],
        }


async def delete_session(session_token: str, pool: asyncpg.Pool) -> None:
    """Delete a session token."""
    if not session_token:
        return
    
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sessions WHERE session_id = $1",
            session_token,
        )


async def delete_user_sessions(user_id: UUID, pool: asyncpg.Pool) -> None:
    """Delete all sessions for a user."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sessions WHERE user_id = $1",
            user_id,
        )


async def get_current_user(
    request: Request,
    access_token: Optional[str] = Cookie(None, alias=JWT_COOKIE_NAME),
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),  # Legacy support
    pool: asyncpg.Pool = Depends(get_pool)
) -> dict:
    """
    Authenticate user using JWT token cookie or HTTP Basic Auth.
    Checks JWT cookie first, then legacy session cookie, then falls back to Basic Auth.
    Raises HTTPException if authentication fails.
    """
    # First, try to authenticate via JWT token cookie
    if access_token:
        user_info = verify_jwt_token(access_token)
        if user_info:
            return user_info
    
    # Fallback to legacy session cookie for backward compatibility
    if session_token:
        user_info = await get_session(session_token, pool)
        if user_info:
            return user_info
    
    # If no valid session, fall back to HTTP Basic Auth
    credentials = await get_optional_credentials(request)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    # Check if this is the admin account from .env
    is_admin_from_env = False
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        if credentials.username == ADMIN_USERNAME and credentials.password == ADMIN_PASSWORD:
            is_admin_from_env = True
    
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            """
            SELECT user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin
            FROM users
            WHERE username = $1
            """,
            credentials.username,
        )
        
        if not user_row:
            # If not found in DB but matches admin env, create admin user entry
            if is_admin_from_env:
                # Create admin user in database with deterministic UUID (UUID v5 based on username)
                # This ensures the same admin username always gets the same UUID, matching migration logic
                password_hash = hash_password(ADMIN_PASSWORD)
                # Generate deterministic UUID v5 from username (same namespace as migration)
                namespace_uuid = UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
                admin_user_id = uuid5(namespace_uuid, ADMIN_USERNAME)
                user_row = await conn.fetchrow(
                    """
                    INSERT INTO users (user_id, username, email, password_hash, is_admin)
                    VALUES ($1, $2, $3, $4, true)
                    ON CONFLICT (username) DO UPDATE SET is_admin = true
                    RETURNING user_id, username, email, password_hash, is_admin
                    """,
                    admin_user_id,
                    ADMIN_USERNAME,
                    f"{ADMIN_USERNAME}@admin.local",
                    password_hash,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password",
                    headers={"WWW-Authenticate": "Basic"},
                )
        else:
            # Verify password (unless it's admin from env)
            if not is_admin_from_env:
                if not verify_password(credentials.password, user_row["password_hash"]):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid username or password",
                        headers={"WWW-Authenticate": "Basic"},
                    )
        
        # Admin status: from env OR from database
        is_admin = is_admin_from_env or (user_row.get("is_admin", False) if user_row else False)
        
        # Convert UUID to string for JSON serialization
        user_id = user_row["user_id"]
        if isinstance(user_id, UUID):
            user_id = str(user_id)
        
        return {
            "user_id": user_id,
            "username": user_row["username"],
            "email": user_row["email"],
            "is_admin": is_admin,
        }


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Dependency to ensure the current user is an admin.
    Raises HTTPException if user is not an admin.
    """
    if not current_user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user

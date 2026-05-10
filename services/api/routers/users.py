# services/api/app/routers/users.py

import os
import logging
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Request
from fastapi.responses import JSONResponse
import asyncpg

from app.db import get_pool
from app.auth import (
    hash_password, 
    verify_password, 
    get_current_user, 
    create_session, 
    delete_session,
    create_jwt_token,
    verify_jwt_token,
    SESSION_COOKIE_NAME,
    JWT_COOKIE_NAME,
    ADMIN_USERNAME,
    ADMIN_PASSWORD
)
from pydantic import BaseModel
from uuid import UUID, uuid5, NAMESPACE_DNS

logger = logging.getLogger(__name__)
router = APIRouter()


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    default_model_id: Optional[int] = None
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    default_top_p: Optional[float] = None
    default_frequency_penalty: Optional[float] = None
    default_presence_penalty: Optional[float] = None


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class UserOut(BaseModel):
    user_id: UUID
    username: str
    email: str
    password_hash: str  # Display hash only
    is_admin: bool = False
    created_at: datetime
    default_model_id: Optional[int] = None
    default_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    default_top_p: Optional[float] = None
    default_frequency_penalty: Optional[float] = None
    default_presence_penalty: Optional[float] = None


@router.get("", response_model=List[UserOut])
async def list_users(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """List all users. Requires authentication. Admin only."""
    # Check if user is admin
    if not current_user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    try:
        rows = await pool.fetch(
            """
            SELECT user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                   default_model_id, default_temperature, default_max_tokens, default_top_p,
                   default_frequency_penalty, default_presence_penalty
            FROM users
            ORDER BY created_at DESC
            """
        )
        
        return [
            UserOut(
                user_id=row["user_id"],
                username=row["username"],
                email=row["email"],
                password_hash=row["password_hash"],
                is_admin=row["is_admin"],
                created_at=row["created_at"],
                default_model_id=row["default_model_id"],
                default_temperature=row["default_temperature"],
                default_max_tokens=row["default_max_tokens"],
                default_top_p=row["default_top_p"],
                default_frequency_penalty=row["default_frequency_penalty"],
                default_presence_penalty=row["default_presence_penalty"],
            )
            for row in rows
        ]
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing users: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: UserCreate,
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Create a new user account. Public endpoint for initial account creation."""
    try:
        # Hash the password
        password_hash = hash_password(user.password)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, email, password_hash, is_admin)
                VALUES ($1, $2, $3, false)
                RETURNING user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                          default_model_id, default_temperature, default_max_tokens, default_top_p,
                          default_frequency_penalty, default_presence_penalty
                """,
                user.username,
                user.email,
                password_hash,
            )
        
        return UserOut(
            user_id=row["user_id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            is_admin=row["is_admin"],
            created_at=row["created_at"],
            default_model_id=row["default_model_id"],
            default_temperature=row["default_temperature"],
            default_max_tokens=row["default_max_tokens"],
            default_top_p=row["default_top_p"],
            default_frequency_penalty=row["default_frequency_penalty"],
            default_presence_penalty=row["default_presence_penalty"],
        )
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists",
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error creating user: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("/login", response_model=UserOut)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Login with username and password. Sets a session cookie for persistence."""
    try:
        # Check if this is the admin account from .env
        is_admin_from_env = False
        if ADMIN_USERNAME and ADMIN_PASSWORD:
            if login_data.username == ADMIN_USERNAME and login_data.password == ADMIN_PASSWORD:
                is_admin_from_env = True
        
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                """
                SELECT user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                       default_model_id, default_temperature, default_max_tokens, default_top_p,
                       default_frequency_penalty, default_presence_penalty
                FROM users
                WHERE username = $1
                """,
                login_data.username,
            )
            
            if not user_row:
                # If not found in DB but matches admin env, create admin user entry
                if is_admin_from_env:
                    password_hash = hash_password(ADMIN_PASSWORD)
                    namespace_uuid = UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
                    admin_user_id = uuid5(namespace_uuid, ADMIN_USERNAME)
                    user_row = await conn.fetchrow(
                        """
                        INSERT INTO users (user_id, username, email, password_hash, is_admin)
                        VALUES ($1, $2, $3, $4, true)
                        ON CONFLICT (username) DO UPDATE SET is_admin = true
                        RETURNING user_id, username, email, password_hash, is_admin, created_at,
                                  default_model_id, default_temperature, default_max_tokens, default_top_p,
                                  default_frequency_penalty, default_presence_penalty
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
                    )
            else:
                # Verify password (unless it's admin from env)
                if not is_admin_from_env:
                    if not verify_password(login_data.password, user_row["password_hash"]):
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid username or password",
                        )
            
            # Admin status: from env OR from database
            is_admin = is_admin_from_env or (user_row.get("is_admin", False) if user_row else False)
            
            # Convert user_id to string for JWT
            user_id = user_row["user_id"]
            if isinstance(user_id, UUID):
                user_id_str = str(user_id)
            else:
                user_id_str = str(user_id)
            
            # Create JWT token
            jwt_token, max_age = create_jwt_token(
                user_id=user_id_str,
                username=user_row["username"],
                email=user_row["email"],
                is_admin=is_admin,
                remember_me=login_data.remember_me
            )
            
            # Determine if we're using HTTPS
            # Check request scheme first (works with X-Forwarded-Proto header from reverse proxy)
            request_scheme = request.url.scheme
            # Also check environment variable and X-Forwarded-Proto header
            use_https = (
                request_scheme == "https" or
                request.headers.get("X-Forwarded-Proto") == "https" or
                os.getenv("USE_HTTPS", "false").lower() == "true"
            )
            
            # Set JWT token in secure, HttpOnly, SameSite=strict cookie (primary security cookie)
            response.set_cookie(
                key=JWT_COOKIE_NAME,
                value=jwt_token,
                max_age=max_age,
                httponly=True,  # Prevent XSS attacks - JavaScript cannot access
                secure=use_https,  # Only send over HTTPS when enabled
                samesite="strict",  # Strict same-site policy for CSRF protection
                path="/",  # Available to all paths
            )
            
            # Also set a non-HttpOnly cookie that Cookie Manager can read for Streamlit
            # This is needed because Streamlit runs server-side and needs to read the token
            # for persistence across page refreshes
            response.set_cookie(
                key=f"{JWT_COOKIE_NAME}_readable",
                value=jwt_token,
                max_age=max_age,
                httponly=False,  # Allow JavaScript/Cookie Manager to read
                secure=use_https,
                samesite="strict",
                path="/",
            )
            
            # Also create legacy session for backward compatibility (optional, can be removed later)
            # This allows existing sessions to continue working during migration
            try:
                user_id_uuid = UUID(user_id_str) if isinstance(user_id_str, str) else user_id
                await create_session(user_id_uuid, pool, remember_me=login_data.remember_me)
            except Exception as e:
                logger.warning(f"Could not create legacy session: {e}")
            
            return UserOut(
                user_id=user_row["user_id"],
                username=user_row["username"],
                email=user_row["email"],
                password_hash=user_row["password_hash"],
                is_admin=is_admin,
                created_at=user_row["created_at"],
                default_model_id=user_row.get("default_model_id"),
                default_temperature=user_row.get("default_temperature"),
                default_max_tokens=user_row.get("default_max_tokens"),
                default_top_p=user_row.get("default_top_p"),
                default_frequency_penalty=user_row.get("default_frequency_penalty"),
                default_presence_penalty=user_row.get("default_presence_penalty"),
            )
    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error during login: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    access_token: Optional[str] = Cookie(None, alias=JWT_COOKIE_NAME),
    session_token: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),  # Legacy support
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Logout and clear JWT and legacy session cookies."""
    # Delete legacy session if exists
    if session_token:
        await delete_session(session_token, pool)
    
    # Determine if we're using HTTPS (same logic as login)
    request_scheme = request.url.scheme
    use_https = (
        request_scheme == "https" or
        request.headers.get("X-Forwarded-Proto") == "https" or
        os.getenv("USE_HTTPS", "false").lower() == "true"
    )
    
    # Clear JWT cookies (both HttpOnly and readable)
    response.delete_cookie(
        key=JWT_COOKIE_NAME,
        httponly=True,
        secure=use_https,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        key=f"{JWT_COOKIE_NAME}_readable",
        httponly=False,
        secure=use_https,
        samesite="strict",
        path="/",
    )
    
    # Clear legacy session cookies (for backward compatibility)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=use_https,
        samesite="lax",
    )
    response.delete_cookie(
        key=f"{SESSION_COOKIE_NAME}_readable",
        httponly=False,
        secure=use_https,
        samesite="lax",
    )
    
    return None


@router.get("/me", response_model=UserOut)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Get current authenticated user's information."""
    try:
        row = await pool.fetchrow(
            """
            SELECT user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                   default_model_id, default_temperature, default_max_tokens, default_top_p,
                   default_frequency_penalty, default_presence_penalty
            FROM users
            WHERE user_id = $1
            """,
            current_user["user_id"],
        )
        
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserOut(
            user_id=row["user_id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            is_admin=row["is_admin"],
            created_at=row["created_at"],
            default_model_id=row["default_model_id"],
            default_temperature=row["default_temperature"],
            default_max_tokens=row["default_max_tokens"],
            default_top_p=row["default_top_p"],
            default_frequency_penalty=row["default_frequency_penalty"],
            default_presence_penalty=row["default_presence_penalty"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting user: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    update: UserUpdate,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Update a user. Users can only update their own account."""
    # Users can only update their own account
    # Convert both to strings for comparison (user_id from path is UUID, current_user["user_id"] is string)
    if str(current_user["user_id"]) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own account",
        )
    
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if user exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM users WHERE user_id = $1",
                    user_id
                )
                if not exists:
                    raise HTTPException(status_code=404, detail="User not found")
                
                # Build update query dynamically
                updates = []
                params = []
                param_idx = 1
                
                if update.email is not None:
                    updates.append(f"email = ${param_idx}")
                    params.append(update.email)
                    param_idx += 1
                
                if update.password is not None:
                    password_hash = hash_password(update.password)
                    updates.append(f"password_hash = ${param_idx}")
                    params.append(password_hash)
                    param_idx += 1

                for field in [
                    "default_model_id", "default_temperature", "default_max_tokens",
                    "default_top_p", "default_frequency_penalty", "default_presence_penalty"
                ]:
                    val = getattr(update, field, None)
                    if val is not None:
                        updates.append(f"{field} = ${param_idx}")
                        params.append(val)
                        param_idx += 1
                
                if updates:
                    params.append(user_id)
                    
                    query = f"""
                        UPDATE users
                        SET {', '.join(updates)}
                        WHERE user_id = ${param_idx}
                        RETURNING user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                                  default_model_id, default_temperature, default_max_tokens, default_top_p,
                                  default_frequency_penalty, default_presence_penalty
                    """
                    
                    row = await conn.fetchrow(query, *params)
                else:
                    # No updates, just fetch existing
                    row = await conn.fetchrow(
                        """
                        SELECT user_id, username, email, password_hash, COALESCE(is_admin, false) as is_admin, created_at,
                               default_model_id, default_temperature, default_max_tokens, default_top_p,
                               default_frequency_penalty, default_presence_penalty
                        FROM users
                        WHERE user_id = $1
                        """,
                        user_id,
                    )
        
        return UserOut(
            user_id=row["user_id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            is_admin=row["is_admin"],
            created_at=row["created_at"],
            default_model_id=row["default_model_id"],
            default_temperature=row["default_temperature"],
            default_max_tokens=row["default_max_tokens"],
            default_top_p=row["default_top_p"],
            default_frequency_penalty=row["default_frequency_penalty"],
            default_presence_penalty=row["default_presence_penalty"],
        )
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error updating user: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Delete a user account. Admins can delete any account except themselves."""
    is_admin = current_user.get("is_admin", False)
    
    # Non-admins can only delete their own account
    if not is_admin:
        if str(current_user["user_id"]) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own account",
            )
    else:
        # Admins cannot delete themselves
        if str(current_user["user_id"]) == str(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins cannot delete their own account",
            )
    
    try:
        result = await pool.execute(
            "DELETE FROM users WHERE user_id = $1",
            user_id
        )
        
        if result.split()[-1] == "0":
            raise HTTPException(status_code=404, detail="User not found")
        
        return None
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error deleting user: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )

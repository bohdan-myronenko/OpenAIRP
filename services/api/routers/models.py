# services/api/app/routers/models.py

import logging
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg

from app.db import get_pool
from app.auth import get_current_user, get_current_admin
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class ModelBase(BaseModel):
    name: str
    api_url: str
    api_key: str
    model_name: str
    custom_prompt: Optional[str] = None
    is_active: bool = False
    description: Optional[str] = None


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class ModelOut(ModelBase):
    model_id: int
    user_id: Optional[str] = None  # None for admin-created models
    is_admin_model: bool = False  # True if user_id is None (admin-created)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[ModelOut])
async def list_models(
    active_only: bool = False,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """List models: admin models (user_id is NULL) + current user's models."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        # Explicitly check if user_id column exists (backward compatibility)
        column_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'models' 
                AND column_name = 'user_id'
            )
        """)
        
        if column_exists:
            # New schema with user_id column
            query = """
                SELECT model_id, user_id, name, api_url, api_key, model_name, custom_prompt, 
                       is_active, description, created_at, updated_at
                FROM models
                WHERE user_id IS NULL OR user_id = $1
            """
            params = [user_id]
            
            if active_only:
                query += " AND is_active = true"
            query += " ORDER BY user_id NULLS FIRST, created_at DESC"
            
            rows = await pool.fetch(query, *params)
        else:
            # Fallback: user_id column doesn't exist yet, return all models (backward compatibility)
            logger.warning("user_id column does not exist in models table, returning all models")
            query = """
                SELECT model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt, 
                       is_active, description, created_at, updated_at
                FROM models
            """
            if active_only:
                query += " WHERE is_active = true"
            query += " ORDER BY created_at DESC"
            rows = await pool.fetch(query)
        
        return [
            ModelOut(
                model_id=row["model_id"],
                user_id=str(row["user_id"]) if row.get("user_id") else None,
                is_admin_model=row.get("user_id") is None,
                name=row["name"],
                api_url=row["api_url"],
                api_key=row["api_key"],
                model_name=row["model_name"],
                custom_prompt=row["custom_prompt"],
                is_active=row["is_active"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    except asyncpg.UndefinedTableError as e:
        logger.error(f"Models table does not exist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Models table does not exist. The table will be created automatically. Please try again in a moment.",
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing models: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error listing models: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        )


@router.get("/active", response_model=ModelOut)
async def get_active_model(
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """Get the currently active model (admin models or user's own models)."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        # Explicitly check if user_id column exists (backward compatibility)
        column_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'models' 
                AND column_name = 'user_id'
            )
        """)
        
        if column_exists:
            row = await pool.fetchrow(
                """
                SELECT model_id, user_id, name, api_url, api_key, model_name, custom_prompt,
                       is_active, description, created_at, updated_at
                FROM models
                WHERE is_active = true AND (user_id IS NULL OR user_id = $1)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                user_id
            )
        else:
            # Fallback: user_id column doesn't exist (backward compatibility)
            row = await pool.fetchrow(
                """
                SELECT model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt,
                       is_active, description, created_at, updated_at
                FROM models
                WHERE is_active = true
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active model found",
            )
        
        return ModelOut(
            model_id=row["model_id"],
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            is_admin_model=row.get("user_id") is None,
            name=row["name"],
            api_url=row["api_url"],
            api_key=row["api_key"],
            model_name=row["model_name"],
            custom_prompt=row["custom_prompt"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting active model: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.get("/admin/all", response_model=List[ModelOut])
async def list_all_models_admin(
    active_only: bool = False,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_admin)
):
    """Admin-only endpoint: List ALL models without user filtering."""
    try:
        # Explicitly check if user_id column exists (backward compatibility)
        column_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'models' 
                AND column_name = 'user_id'
            )
        """)
        
        if column_exists:
            query = """
                SELECT model_id, user_id, name, api_url, api_key, model_name, custom_prompt, 
                       is_active, description, created_at, updated_at
                FROM models
            """
            
            if active_only:
                query += " WHERE is_active = true"
            query += " ORDER BY user_id NULLS FIRST, created_at DESC"
            
            rows = await pool.fetch(query)
        else:
            # Fallback: user_id column doesn't exist yet, return all models (backward compatibility)
            logger.warning("user_id column does not exist in models table, returning all models")
            query = """
                SELECT model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt, 
                       is_active, description, created_at, updated_at
                FROM models
            """
            if active_only:
                query += " WHERE is_active = true"
            query += " ORDER BY created_at DESC"
            rows = await pool.fetch(query)
        
        return [
            ModelOut(
                model_id=row["model_id"],
                user_id=str(row["user_id"]) if row.get("user_id") else None,
                is_admin_model=row.get("user_id") is None,
                name=row["name"],
                api_url=row["api_url"],
                api_key=row["api_key"],
                model_name=row["model_name"],
                custom_prompt=row["custom_prompt"],
                is_active=row["is_active"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    except asyncpg.UndefinedTableError as e:
        logger.error(f"Models table does not exist: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Models table does not exist. The table will be created automatically. Please try again in a moment.",
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing models: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error listing models: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        )


@router.post("", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    model: ModelCreate,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """Create a new model. Models created by users are private to that user."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        # If this is set as active, deactivate all others for this user
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if user_id column exists (backward compatibility)
                column_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = 'public' 
                        AND table_name = 'models' 
                        AND column_name = 'user_id'
                    )
                """)
                
                if column_exists:
                    # New schema with user_id column
                    if model.is_active:
                        # Only deactivate user's own models, not admin models
                        await conn.execute(
                            "UPDATE models SET is_active = false WHERE is_active = true AND user_id = $1",
                            user_id
                        )
                    
                    row = await conn.fetchrow(
                        """
                        INSERT INTO models (user_id, name, api_url, api_key, model_name, custom_prompt, 
                                          is_active, description, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                        RETURNING model_id, user_id, name, api_url, api_key, model_name, custom_prompt,
                                  is_active, description, created_at, updated_at
                        """,
                        user_id,
                        model.name,
                        model.api_url,
                        model.api_key,
                        model.model_name,
                        model.custom_prompt,
                        model.is_active,
                        model.description,
                    )
                else:
                    # Old schema without user_id column (backward compatibility)
                    logger.warning("user_id column does not exist in models table, creating model without user_id")
                    if model.is_active:
                        await conn.execute(
                            "UPDATE models SET is_active = false WHERE is_active = true"
                        )
                    
                    row = await conn.fetchrow(
                        """
                        INSERT INTO models (name, api_url, api_key, model_name, custom_prompt, 
                                          is_active, description, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                        RETURNING model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt,
                                  is_active, description, created_at, updated_at
                        """,
                        model.name,
                        model.api_url,
                        model.api_key,
                        model.model_name,
                        model.custom_prompt,
                        model.is_active,
                        model.description,
                    )
        
        return ModelOut(
            model_id=row["model_id"],
            user_id=str(row["user_id"]) if row["user_id"] else None,
            is_admin_model=row["user_id"] is None,
            name=row["name"],
            api_url=row["api_url"],
            api_key=row["api_key"],
            model_name=row["model_name"],
            custom_prompt=row["custom_prompt"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error creating model: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(
    model_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """Get a specific model by ID. Users can only access admin models or their own models."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        # Explicitly check if user_id column exists (backward compatibility)
        column_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'models' 
                AND column_name = 'user_id'
            )
        """)
        
        if column_exists:
            row = await pool.fetchrow(
                """
                SELECT model_id, user_id, name, api_url, api_key, model_name, custom_prompt,
                       is_active, description, created_at, updated_at
                FROM models
                WHERE model_id = $1 AND (user_id IS NULL OR user_id = $2)
                """,
                model_id,
                user_id,
            )
        else:
            # Fallback: user_id column doesn't exist (backward compatibility)
            row = await pool.fetchrow(
                """
                SELECT model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt,
                       is_active, description, created_at, updated_at
                FROM models
                WHERE model_id = $1
                """,
                model_id,
            )
        
        if not row:
            raise HTTPException(status_code=404, detail="Model not found")
        
        return ModelOut(
            model_id=row["model_id"],
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            is_admin_model=row.get("user_id") is None,
            name=row["name"],
            api_url=row["api_url"],
            api_key=row["api_key"],
            model_name=row["model_name"],
            custom_prompt=row["custom_prompt"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting model: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.put("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: int,
    update: ModelUpdate,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """Update a model. Users can only update their own models, not admin models."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        is_admin = current_user.get("is_admin", False)
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if user_id column exists (backward compatibility)
                column_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_schema = 'public' 
                        AND table_name = 'models' 
                        AND column_name = 'user_id'
                    )
                """)
                
                if column_exists:
                    # Check if model exists and belongs to user (or is admin model)
                    model_row = await conn.fetchrow(
                        "SELECT user_id FROM models WHERE model_id = $1",
                        model_id
                    )
                    if not model_row:
                        raise HTTPException(status_code=404, detail="Model not found")
                    
                    # Users can only update their own models (not admin models)
                    if model_row["user_id"] is None:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cannot update admin-created models"
                        )
                    if str(model_row["user_id"]) != str(user_id):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cannot update models owned by other users"
                        )
                    
                    # If setting as active, deactivate all others for this user
                    if update.is_active is True:
                        await conn.execute(
                            "UPDATE models SET is_active = false WHERE is_active = true AND model_id != $1 AND user_id = $2",
                            model_id,
                            user_id
                        )
                else:
                    # Old schema without user_id - just verify model exists
                    model_row = await conn.fetchrow(
                        "SELECT model_id FROM models WHERE model_id = $1",
                        model_id
                    )
                    if not model_row:
                        raise HTTPException(status_code=404, detail="Model not found")
                    
                    # If setting as active, deactivate all others
                    if update.is_active is True:
                        await conn.execute(
                            "UPDATE models SET is_active = false WHERE is_active = true AND model_id != $1",
                            model_id
                        )
                
                # Build update query dynamically
                updates = []
                params = []
                param_idx = 1
                
                if update.name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(update.name)
                    param_idx += 1
                
                if update.api_url is not None:
                    updates.append(f"api_url = ${param_idx}")
                    params.append(update.api_url)
                    param_idx += 1
                
                if update.api_key is not None:
                    updates.append(f"api_key = ${param_idx}")
                    params.append(update.api_key)
                    param_idx += 1
                
                if update.model_name is not None:
                    updates.append(f"model_name = ${param_idx}")
                    params.append(update.model_name)
                    param_idx += 1
                
                if update.custom_prompt is not None:
                    updates.append(f"custom_prompt = ${param_idx}")
                    params.append(update.custom_prompt)
                    param_idx += 1
                
                if update.is_active is not None:
                    updates.append(f"is_active = ${param_idx}")
                    params.append(update.is_active)
                    param_idx += 1
                
                if update.description is not None:
                    updates.append(f"description = ${param_idx}")
                    params.append(update.description)
                    param_idx += 1
                
                if updates:
                    updates.append(f"updated_at = NOW()")
                    params.append(model_id)
                    
                    if column_exists:
                        query = f"""
                            UPDATE models
                            SET {', '.join(updates)}
                            WHERE model_id = ${param_idx}
                            RETURNING model_id, user_id, name, api_url, api_key, model_name, custom_prompt,
                                      is_active, description, created_at, updated_at
                        """
                    else:
                        query = f"""
                            UPDATE models
                            SET {', '.join(updates)}
                            WHERE model_id = ${param_idx}
                            RETURNING model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt,
                                      is_active, description, created_at, updated_at
                        """
                    
                    row = await conn.fetchrow(query, *params)
                else:
                    # No updates, just fetch existing
                    if column_exists:
                        row = await conn.fetchrow(
                            """
                            SELECT model_id, user_id, name, api_url, api_key, model_name, custom_prompt,
                                   is_active, description, created_at, updated_at
                            FROM models
                            WHERE model_id = $1
                            """,
                            model_id,
                        )
                    else:
                        row = await conn.fetchrow(
                            """
                            SELECT model_id, NULL::UUID as user_id, name, api_url, api_key, model_name, custom_prompt,
                                   is_active, description, created_at, updated_at
                            FROM models
                            WHERE model_id = $1
                            """,
                            model_id,
                        )
        
        return ModelOut(
            model_id=row["model_id"],
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            is_admin_model=row.get("user_id") is None,
            name=row["name"],
            api_url=row["api_url"],
            api_key=row["api_key"],
            model_name=row["model_name"],
            custom_prompt=row["custom_prompt"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error updating model: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
    current_user: dict = Depends(get_current_user)
):
    """Delete a model. Users can only delete their own models, not admin models."""
    try:
        user_id = current_user.get("user_id")
        if isinstance(user_id, str):
            user_id = UUID(user_id)
        
        # Check if user_id column exists (backward compatibility)
        column_exists = await pool.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'models' 
                AND column_name = 'user_id'
            )
        """)
        
        if column_exists:
            # Check if model exists and belongs to user
            model_row = await pool.fetchrow(
                "SELECT user_id FROM models WHERE model_id = $1",
                model_id
            )
            if not model_row:
                raise HTTPException(status_code=404, detail="Model not found")
            
            # Users can only delete their own models (not admin models)
            if model_row["user_id"] is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot delete admin-created models"
                )
            if str(model_row["user_id"]) != str(user_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot delete models owned by other users"
                )
            
            result = await pool.execute(
                "DELETE FROM models WHERE model_id = $1 AND user_id = $2",
                model_id,
                user_id
            )
        else:
            # Old schema without user_id - just delete if exists
            model_row = await pool.fetchrow(
                "SELECT model_id FROM models WHERE model_id = $1",
                model_id
            )
            if not model_row:
                raise HTTPException(status_code=404, detail="Model not found")
            
            result = await pool.execute(
                "DELETE FROM models WHERE model_id = $1",
                model_id
            )
        
        if result.split()[-1] == "0":
            raise HTTPException(status_code=404, detail="Model not found")
        
        return None
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error deleting model: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )

# services/api/app/routers/personas.py

import logging
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
import asyncpg

from app.db import get_pool
from app.auth import get_current_user
from app.utils import save_profile_picture, delete_profile_picture
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class PersonaBase(BaseModel):
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    is_default: bool = False


class PersonaCreate(PersonaBase):
    pass  # user_id will be set from authenticated user


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    is_default: Optional[bool] = None


class PersonaOut(PersonaBase):
    persona_id: int
    user_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[PersonaOut])
async def list_personas(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """List all personas for the authenticated user."""
    try:
        rows = await pool.fetch(
            """
            SELECT persona_id, user_id, name, description, avatar_url, is_default, created_at
            FROM personas
            WHERE user_id = $1
            ORDER BY is_default DESC, created_at DESC
            """,
            current_user["user_id"],
        )
        
        return [
            PersonaOut(
                persona_id=row["persona_id"],
                user_id=row["user_id"],
                name=row["name"],
                description=row["description"],
                avatar_url=row["avatar_url"],
                is_default=row["is_default"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing personas: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    persona: PersonaCreate,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Create a new persona for the authenticated user."""
    try:
        # If this is set as default, unset others for this user
        async with pool.acquire() as conn:
            async with conn.transaction():
                if persona.is_default:
                    await conn.execute(
                        "UPDATE personas SET is_default = false WHERE is_default = true AND user_id = $1",
                        current_user["user_id"]
                    )
                
                row = await conn.fetchrow(
                    """
                    INSERT INTO personas (user_id, name, description, avatar_url, is_default)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING persona_id, user_id, name, description, avatar_url, is_default, created_at
                    """,
                    current_user["user_id"],
                    persona.name,
                    persona.description,
                    persona.avatar_url,
                    persona.is_default,
                )
        
        return PersonaOut(
            persona_id=row["persona_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            avatar_url=row["avatar_url"],
            is_default=row["is_default"],
            created_at=row["created_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error creating persona: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.get("/{persona_id}", response_model=PersonaOut)
async def get_persona(
    persona_id: int,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Get a specific persona by ID. Users can only access their own personas."""
    try:
        row = await pool.fetchrow(
            """
            SELECT persona_id, user_id, name, description, avatar_url, is_default, created_at
            FROM personas
            WHERE persona_id = $1 AND user_id = $2
            """,
            persona_id,
            current_user["user_id"],
        )
        
        if not row:
            raise HTTPException(status_code=404, detail="Persona not found")
        
        return PersonaOut(
            persona_id=row["persona_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            avatar_url=row["avatar_url"],
            is_default=row["is_default"],
            created_at=row["created_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting persona: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.put("/{persona_id}", response_model=PersonaOut)
async def update_persona(
    persona_id: int,
    update: PersonaUpdate,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Update a persona. Users can only update their own personas."""
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if persona exists and belongs to user
                exists = await conn.fetchval(
                    "SELECT 1 FROM personas WHERE persona_id = $1 AND user_id = $2",
                    persona_id,
                    current_user["user_id"]
                )
                if not exists:
                    raise HTTPException(status_code=404, detail="Persona not found")
                
                # If setting as default, unset others for this user
                if update.is_default is True:
                    await conn.execute(
                        "UPDATE personas SET is_default = false WHERE is_default = true AND persona_id != $1 AND user_id = $2",
                        persona_id,
                        current_user["user_id"]
                    )
                
                # Build update query dynamically
                updates = []
                params = []
                param_idx = 1
                
                if update.name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(update.name)
                    param_idx += 1
                
                if update.description is not None:
                    updates.append(f"description = ${param_idx}")
                    params.append(update.description)
                    param_idx += 1
                
                if update.avatar_url is not None:
                    updates.append(f"avatar_url = ${param_idx}")
                    params.append(update.avatar_url)
                    param_idx += 1
                
                if update.is_default is not None:
                    updates.append(f"is_default = ${param_idx}")
                    params.append(update.is_default)
                    param_idx += 1
                
                if updates:
                    params.append(persona_id)
                    
                    query = f"""
                        UPDATE personas
                        SET {', '.join(updates)}
                        WHERE persona_id = ${param_idx}
                        RETURNING persona_id, user_id, name, description, avatar_url, is_default, created_at
                    """
                    
                    row = await conn.fetchrow(query, *params)
                else:
                    # No updates, just fetch existing
                    row = await conn.fetchrow(
                        """
                        SELECT persona_id, user_id, name, description, avatar_url, is_default, created_at
                        FROM personas
                        WHERE persona_id = $1
                        """,
                        persona_id,
                    )
        
        return PersonaOut(
            persona_id=row["persona_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            avatar_url=row["avatar_url"],
            is_default=row["is_default"],
            created_at=row["created_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error updating persona: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: int,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Delete a persona. Users can only delete their own personas."""
    try:
        # Get avatar_url before deleting
        persona_row = await pool.fetchrow(
            "SELECT avatar_url FROM personas WHERE persona_id = $1 AND user_id = $2",
            persona_id,
            current_user["user_id"]
        )
        
        if not persona_row:
            raise HTTPException(status_code=404, detail="Persona not found")
        
        result = await pool.execute(
            "DELETE FROM personas WHERE persona_id = $1 AND user_id = $2",
            persona_id,
            current_user["user_id"]
        )
        
        # Delete profile picture if it exists
        if persona_row["avatar_url"]:
            delete_profile_picture(persona_row["avatar_url"])
        
        return None
    except HTTPException:
        raise
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error deleting persona: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("/{persona_id}/avatar", response_model=PersonaOut)
async def upload_persona_avatar(
    persona_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Upload a profile picture for a persona. Users can only upload for their own personas."""
    try:
        # Check if persona exists and belongs to user
        persona = await get_persona(persona_id, current_user, pool)
        
        # Delete old avatar if it exists
        if persona.avatar_url:
            delete_profile_picture(persona.avatar_url)
        
        # Save new avatar
        avatar_url = await save_profile_picture(file, "personas", persona_id)
        
        # Update persona in database
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE personas
                SET avatar_url = $1
                WHERE persona_id = $2 AND user_id = $3
                RETURNING persona_id, user_id, name, description, avatar_url, is_default, created_at
                """,
                avatar_url,
                persona_id,
                current_user["user_id"]
            )
        
        return PersonaOut(
            persona_id=row["persona_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            avatar_url=row["avatar_url"],
            is_default=row["is_default"],
            created_at=row["created_at"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading persona avatar: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading avatar: {str(e)}"
        )

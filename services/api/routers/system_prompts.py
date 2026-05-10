# services/api/app/routers/system_prompts.py

import logging
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg

from app.db import get_pool
from app.auth import get_current_admin
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class SystemPromptBase(BaseModel):
    name: str
    content: str
    is_active: bool = True
    description: Optional[str] = None


class SystemPromptCreate(SystemPromptBase):
    pass


class SystemPromptUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class SystemPromptOut(SystemPromptBase):
    prompt_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[SystemPromptOut])
async def list_system_prompts(
    active_only: bool = False,
    pool: asyncpg.Pool = Depends(get_pool)
):
    """List all system prompts, optionally filtered to active ones only."""
    try:
        query = """
            SELECT prompt_id, name, content, is_active, description, created_at, updated_at
            FROM system_prompts
        """
        if active_only:
            query += " WHERE is_active = true"
        query += " ORDER BY created_at DESC"
        
        rows = await pool.fetch(query)
        
        return [
            SystemPromptOut(
                prompt_id=row["prompt_id"],
                name=row["name"],
                content=row["content"],
                is_active=row["is_active"],
                description=row["description"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing system prompts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.get("/active", response_model=SystemPromptOut)
async def get_active_system_prompt(pool: asyncpg.Pool = Depends(get_pool)):
    """Get the currently active system prompt."""
    try:
        row = await pool.fetchrow(
            """
            SELECT prompt_id, name, content, is_active, description, created_at, updated_at
            FROM system_prompts
            WHERE is_active = true
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active system prompt found",
            )
        
        return SystemPromptOut(
            prompt_id=row["prompt_id"],
            name=row["name"],
            content=row["content"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting active system prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.post("", response_model=SystemPromptOut, status_code=status.HTTP_201_CREATED)
async def create_system_prompt(
    prompt: SystemPromptCreate,
    current_admin: dict = Depends(get_current_admin),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Create a new system prompt. Admin only."""
    try:
        # If this is set as active, deactivate all others
        async with pool.acquire() as conn:
            async with conn.transaction():
                if prompt.is_active:
                    await conn.execute(
                        "UPDATE system_prompts SET is_active = false WHERE is_active = true"
                    )
                
                row = await conn.fetchrow(
                    """
                    INSERT INTO system_prompts (name, content, is_active, description, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    RETURNING prompt_id, name, content, is_active, description, created_at, updated_at
                    """,
                    prompt.name,
                    prompt.content,
                    prompt.is_active,
                    prompt.description,
                )
        
        return SystemPromptOut(
            prompt_id=row["prompt_id"],
            name=row["name"],
            content=row["content"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error creating system prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.get("/{prompt_id}", response_model=SystemPromptOut)
async def get_system_prompt(
    prompt_id: int,
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Get a specific system prompt by ID."""
    try:
        row = await pool.fetchrow(
            """
            SELECT prompt_id, name, content, is_active, description, created_at, updated_at
            FROM system_prompts
            WHERE prompt_id = $1
            """,
            prompt_id,
        )
        
        if not row:
            raise HTTPException(status_code=404, detail="System prompt not found")
        
        return SystemPromptOut(
            prompt_id=row["prompt_id"],
            name=row["name"],
            content=row["content"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error getting system prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.put("/{prompt_id}", response_model=SystemPromptOut)
async def update_system_prompt(
    prompt_id: int,
    update: SystemPromptUpdate,
    current_admin: dict = Depends(get_current_admin),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Update a system prompt. Admin only."""
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if prompt exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM system_prompts WHERE prompt_id = $1",
                    prompt_id
                )
                if not exists:
                    raise HTTPException(status_code=404, detail="System prompt not found")
                
                # If setting as active, deactivate all others
                if update.is_active is True:
                    await conn.execute(
                        "UPDATE system_prompts SET is_active = false WHERE is_active = true AND prompt_id != $1",
                        prompt_id
                    )
                
                # Build update query dynamically
                updates = []
                params = []
                param_idx = 1
                
                if update.name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(update.name)
                    param_idx += 1
                
                if update.content is not None:
                    updates.append(f"content = ${param_idx}")
                    params.append(update.content)
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
                    params.append(prompt_id)
                    
                    query = f"""
                        UPDATE system_prompts
                        SET {', '.join(updates)}
                        WHERE prompt_id = ${param_idx}
                        RETURNING prompt_id, name, content, is_active, description, created_at, updated_at
                    """
                    
                    row = await conn.fetchrow(query, *params)
                else:
                    # No updates, just fetch existing
                    row = await conn.fetchrow(
                        """
                        SELECT prompt_id, name, content, is_active, description, created_at, updated_at
                        FROM system_prompts
                        WHERE prompt_id = $1
                        """,
                        prompt_id,
                    )
        
        return SystemPromptOut(
            prompt_id=row["prompt_id"],
            name=row["name"],
            content=row["content"],
            is_active=row["is_active"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error updating system prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system_prompt(
    prompt_id: int,
    current_admin: dict = Depends(get_current_admin),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Delete a system prompt. Admin only."""
    try:
        result = await pool.execute(
            "DELETE FROM system_prompts WHERE prompt_id = $1",
            prompt_id
        )
        
        if result.split()[-1] == "0":
            raise HTTPException(status_code=404, detail="System prompt not found")
        
        return None
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error deleting system prompt: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )

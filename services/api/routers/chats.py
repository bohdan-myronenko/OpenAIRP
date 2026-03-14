# services/api/app/routers/chats.py

import os
import logging
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import asyncpg
import httpx

from app.db import get_pool
from app.utils import generate_short_uuid
from app.auth import get_current_user, get_current_admin
from app.schemas import (
    ChatCreate,
    ChatDetail,
    ChatSummary,
    ChatMessageIn,
    ChatMessageResponse,
    MessageOut,
    MessageUpdate,
)

# Helper function to convert UUID to string for JSON serialization
def uuid_to_str(val):
    """Convert UUID objects to strings for JSON serialization."""
    if isinstance(val, UUID):
        return str(val)
    return val

logger = logging.getLogger(__name__)
router = APIRouter()

# Worker service URL
WORKER_URL = os.getenv("WORKER_URL", "http://localhost:8081").rstrip("/")

import asyncio

# Store active streaming requests for kill switch functionality
# Format: {chat_id: {user_message_id: asyncio.Event}}
_active_streams: Dict[str, Dict[int, asyncio.Event]] = {}


async def _fetch_chat_detail(
    pool: asyncpg.Pool, chat_id: str, user_id: Optional[int] = None
) -> ChatDetail | None:
    async with pool.acquire() as conn:
        # Ensure reroll columns exist (fallback if migration/startup didn't create them)
        try:
            # Try to add columns if they don't exist - use DO block to handle gracefully
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'messages' AND column_name = 'parent_message_id'
                    ) THEN
                        ALTER TABLE messages ADD COLUMN parent_message_id INTEGER REFERENCES messages(message_id) ON DELETE CASCADE;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'messages' AND column_name = 'attempt_number'
                    ) THEN
                        ALTER TABLE messages ADD COLUMN attempt_number INTEGER DEFAULT 0;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'messages' AND column_name = 'is_selected'
                    ) THEN
                        ALTER TABLE messages ADD COLUMN is_selected BOOLEAN DEFAULT true;
                    END IF;
                END $$;
            """)
            
            # Create index and update existing rows
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_message_id, attempt_number)
            """)
            await conn.execute("""
                UPDATE messages SET attempt_number = COALESCE(attempt_number, 0), is_selected = COALESCE(is_selected, true) 
                WHERE attempt_number IS NULL OR is_selected IS NULL
            """)
        except Exception as e:
            logger.error(f"Could not ensure reroll columns exist: {e}", exc_info=True)
            raise
        
        query = """
            SELECT c.chat_id,
                   c.title,
                   c.bot_id,
                   c.persona_id,
                   c.user_id,
                   COALESCE(b.name, 'Unknown Bot') AS bot_name,
                   p.name AS persona_name
            FROM chats c
            LEFT JOIN bots b ON b.bot_id = c.bot_id
            LEFT JOIN personas p ON p.persona_id = c.persona_id
            WHERE c.chat_id = $1::text
        """
        params = [chat_id]
        
        # Add user filter if provided
        if user_id is not None:
            # Convert user_id to UUID if it's a string
            if isinstance(user_id, str):
                from uuid import UUID
                user_id = UUID(user_id)
            query += " AND c.user_id = $2::uuid"
            params.append(user_id)
        
        chat_row = await conn.fetchrow(query, *params)
        if not chat_row:
            return None

        try:
            msg_rows = await conn.fetch(
                """
                SELECT message_id,
                       sender_type AS sender,
                       content,
                       created_at,
                       parent_message_id,
                       attempt_number,
                       is_selected
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at ASC, message_id ASC
                """,
                chat_id,
            )
        except Exception as e:
            logger.error(f"Error querying messages: {e}", exc_info=True)
            raise
        
        # Get total attempts for each message that has rerolls
        # Count includes parent message + all reroll attempts
        # A parent message has parent_message_id = NULL or parent_message_id = message_id
        parent_ids = []
        for row in msg_rows:
            if row["parent_message_id"] is None or row["parent_message_id"] == row["message_id"]:
                parent_ids.append(row["message_id"])
        
        total_attempts_map = {}
        if parent_ids:
            attempt_counts = await conn.fetch(
                """
                SELECT 
                    COALESCE(NULLIF(parent_message_id, message_id), message_id) as parent_id,
                    COUNT(*) as total
                FROM messages
                WHERE (parent_message_id = ANY($1::int[]) OR message_id = ANY($1::int[]))
                  AND chat_id = $2::text::text
                GROUP BY COALESCE(NULLIF(parent_message_id, message_id), message_id)
                """,
                parent_ids,
                chat_id,
            )
            total_attempts_map = {row["parent_id"]: row["total"] for row in attempt_counts}

    history: List[MessageOut] = []
    for row in msg_rows:
        # Only include selected attempts or messages without rerolls
        # A message is a parent if parent_message_id is NULL or equals message_id
        is_parent = row["parent_message_id"] is None or row["parent_message_id"] == row["message_id"]
        # Include if: selected, OR it's a parent with no rerolls (parent_message_id is NULL, meaning never rerolled)
        # Exclude parent messages that have been rerolled (parent_message_id = message_id) unless they're selected
        should_include = row["is_selected"] or (is_parent and row["parent_message_id"] is None)
        
        if should_include:
            # Determine parent ID: if parent_message_id is NULL or equals message_id, this IS the parent
            parent_id = row["message_id"] if is_parent else row["parent_message_id"]
            total_attempts = total_attempts_map.get(parent_id) if parent_id in total_attempts_map else (1 if is_parent else None)
            history.append(MessageOut(
                message_id=row["message_id"],
                sender=row["sender"],
                content=row["content"],
                created_at=row["created_at"],
                parent_message_id=row["parent_message_id"],
                attempt_number=row["attempt_number"],
                is_selected=row["is_selected"],
                total_attempts=total_attempts,
            ))

    return ChatDetail(
        chat_id=chat_row["chat_id"],
        title=chat_row["title"],
        bot_id=chat_row["bot_id"],
        bot_name=chat_row["bot_name"],
        persona_id=chat_row["persona_id"],
        persona_name=chat_row["persona_name"],
        history=history,
    )


@router.get("", response_model=List[ChatSummary])
async def list_chats(
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """List all chats for the authenticated user."""
    rows = await pool.fetch(
        """
        SELECT c.chat_id,
               c.title,
               c.bot_id,
               COALESCE(b.name, 'Unknown Bot') AS bot_name,
               c.last_used,
               c.persona_id,
               p.avatar_url AS persona_avatar_url,
               (SELECT COUNT(*) FROM messages WHERE chat_id = c.chat_id) AS message_count
        FROM chats c
        LEFT JOIN bots b ON b.bot_id = c.bot_id
        LEFT JOIN personas p ON p.persona_id = c.persona_id
        WHERE c.user_id = $1::uuid
        ORDER BY c.last_used DESC NULLS LAST, c.chat_id DESC
        """,
        current_user["user_id"],
    )

    result = []
    for idx, row in enumerate(rows):
        # Skip rows with NULL chat_id (data integrity issue)
        if row.get("chat_id") is None:
            logger.warning(f"Skipping chat with NULL chat_id for user {current_user['user_id']}")
            continue
        result.append(ChatSummary(
            chat_id=row["chat_id"],
            title=row["title"] or "Untitled",
            bot_id=row["bot_id"],
            bot_name=row["bot_name"] or "Unknown Bot",
            last_used=row["last_used"],
            persona_id=row["persona_id"],
            persona_avatar_url=row["persona_avatar_url"],
            message_count=row["message_count"],
        ))
    return result


@router.post("", response_model=ChatDetail, status_code=status.HTTP_201_CREATED)
async def create_chat(
    payload: ChatCreate,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    async with pool.acquire() as conn:
        # Check column type first to detect if migration is needed
        try:
            col_info = await conn.fetchrow("""
                SELECT data_type, character_maximum_length 
                FROM information_schema.columns 
                WHERE table_name = 'chats' AND column_name = 'chat_id'
            """)
        except Exception:
            col_info = None
        
        async with conn.transaction():
            # ensure bot exists and get its name and greeting
            bot_row = await conn.fetchrow(
                "SELECT bot_id, name, greeting FROM bots WHERE bot_id = $1",
                payload.bot_id,
            )
            if not bot_row:
                raise HTTPException(status_code=404, detail="Bot not found")

            bot_name = bot_row["name"]
            bot_greeting = bot_row["greeting"]
            title = payload.title or f"Chat with {bot_name}"

            # Generate a short UUID for the chat
            chat_id = generate_short_uuid()
            
            # Check if migration is needed
            if col_info and col_info["data_type"] == "integer":
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Database migration required: chat_id column is still INTEGER. Please run migration 004_change_chat_id_to_uuid.sql or restart services to apply migrations."
                )
            
            # Verify persona belongs to user if provided
            if payload.persona_id:
                persona_check = await conn.fetchrow(
                    "SELECT user_id FROM personas WHERE persona_id = $1",
                    payload.persona_id
                )
                if not persona_check:
                    raise HTTPException(status_code=404, detail="Persona not found")
                if str(persona_check["user_id"]) != str(current_user["user_id"]):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You can only use your own personas"
                    )
            
            # Get persona name for tag replacement
            persona_name = "User"
            if payload.persona_id:
                persona_row = await conn.fetchrow(
                    "SELECT name FROM personas WHERE persona_id = $1",
                    payload.persona_id
                )
                if persona_row:
                    persona_name = persona_row["name"]
            
            try:
                chat_row = await conn.fetchrow(
                    """
                    INSERT INTO chats (chat_id, user_id, bot_id, persona_id, title, last_used)
                    VALUES ($1::text, $2, $3, $4, $5, NOW())
                    RETURNING chat_id, title, bot_id
                    """,
                    chat_id,
                    current_user["user_id"],
                    payload.bot_id,
                    payload.persona_id,
                    title,
                )
                
                # Insert greeting message if it exists (as first bot message, non-editable/non-deletable)
                if bot_greeting:
                    # Replace {{char}} and {{user}} tags in greeting
                    greeting_content = bot_greeting.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
                    await conn.execute(
                        """
                        INSERT INTO messages (chat_id, sender_type, content)
                        VALUES ($1::text, 'bot', $2)
                        """,
                        chat_id,
                        greeting_content,
                    )
            except asyncpg.exceptions.PostgresError as e:
                # Check if it's a type mismatch error
                if "is of type integer but expression is of type text" in str(e) or "is of type integer" in str(e):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Database migration required: chat_id column is still INTEGER. Please run migration 004_change_chat_id_to_uuid.sql or restart services to apply migrations."
                    )
                raise
            chat_id = chat_row["chat_id"]
            
            # Fetch persona info if persona_id was set (inside transaction to ensure consistency)
            # Note: persona_name was already fetched earlier (lines 353-360), but we fetch again here
            # to ensure we have the latest value after the transaction commits
            if payload.persona_id:
                persona_row = await conn.fetchrow(
                    "SELECT name FROM personas WHERE persona_id = $1",
                    payload.persona_id
                )
                if persona_row:
                    persona_name = persona_row["name"]
            
            # Store values for return after transaction commits
            saved_chat_id = chat_id
            saved_title = chat_row["title"]
            saved_bot_id = chat_row["bot_id"]
            saved_bot_name = bot_name
            saved_persona_id = payload.persona_id
            saved_persona_name = persona_name
            # Transaction commits automatically here when context exits
    
    # Fetch chat detail to include greeting message in history
    chat_detail = await _fetch_chat_detail(pool, saved_chat_id, current_user["user_id"])
    if chat_detail:
        return chat_detail
    
    # Fallback if fetch fails
    return ChatDetail(
        chat_id=saved_chat_id,
        title=saved_title,
        bot_id=saved_bot_id,
        bot_name=saved_bot_name,
        persona_id=saved_persona_id,
        persona_name=saved_persona_name,
        history=[],
    )


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Get a specific chat. Users can only access their own chats."""
    chat = await _fetch_chat_detail(pool, chat_id, current_user["user_id"])
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.get("/admin/user/{user_id}", response_model=List[ChatSummary])
async def admin_list_user_chats(
    user_id: UUID,
    current_admin: dict = Depends(get_current_admin),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """List all chats for a specific user. Admin only."""
    rows = await pool.fetch(
        """
        SELECT c.chat_id,
               c.title,
               c.bot_id,
               COALESCE(b.name, 'Unknown Bot') AS bot_name,
               c.last_used,
               c.persona_id,
               p.avatar_url AS persona_avatar_url,
               (SELECT COUNT(*) FROM messages WHERE chat_id = c.chat_id) AS message_count
        FROM chats c
        LEFT JOIN bots b ON b.bot_id = c.bot_id
        LEFT JOIN personas p ON p.persona_id = c.persona_id
        WHERE c.user_id = $1::uuid
        ORDER BY c.last_used DESC NULLS LAST, c.chat_id DESC
        """,
        user_id,
    )

    result = []
    for row in rows:
        # Skip rows with NULL chat_id (data integrity issue)
        if row.get("chat_id") is None:
            logger.warning(f"Skipping chat with NULL chat_id for user {user_id} in admin view")
            continue
        result.append(ChatSummary(
            chat_id=row["chat_id"],
            title=row["title"] or "Untitled",
            bot_id=row["bot_id"],
            bot_name=row["bot_name"] or "Unknown Bot",
            last_used=row["last_used"],
            persona_id=row["persona_id"],
            persona_avatar_url=row["persona_avatar_url"],
            message_count=row["message_count"],
        ))
    return result


@router.get("/admin/{chat_id}", response_model=ChatDetail)
async def admin_get_chat(
    chat_id: str,
    current_admin: dict = Depends(get_current_admin),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Get a specific chat by ID. Admin only - bypasses user ownership check."""
    chat = await _fetch_chat_detail(pool, chat_id, user_id=None)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Delete a chat and all its messages."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Delete all messages first (foreign key constraint)
            await conn.execute(
                "DELETE FROM messages WHERE chat_id = $1::text",
                chat_id
            )
            
            # Delete the chat (only if owned by user)
            result = await conn.execute(
                "DELETE FROM chats WHERE chat_id = $1::text AND user_id = $2::uuid",
                chat_id,
                current_user["user_id"]
            )
            
            # result is like "DELETE 1"
            if result.split()[-1] == "0":
                raise HTTPException(status_code=404, detail="Chat not found")
    
    return None


async def _generate_bot_reply(
    chat_id: str,
    user_message: str,
    pool: asyncpg.Pool,
    user_id: UUID,
    generation_settings: Optional[Dict[str, Any]] = None,
    exclude_last_bot_message: bool = False,
) -> str:
    """
    Generate bot reply by calling the worker service with:
    - Chat history
    - Bot persona
    - User persona (if available)
    - Active system prompt
    - Generation settings
    """
    async with pool.acquire() as conn:
        # Fetch chat details with bot persona, bot name, user persona, persona name, scenario, and example_dialog
        chat_data = await conn.fetchrow(
            """
            SELECT c.chat_id,
                   c.bot_id,
                   c.persona_id,
                   c.user_id,
                   b.persona AS bot_persona,
                   COALESCE(b.name, 'Unknown Bot') AS bot_name,
                   p.description AS user_persona,
                   p.name AS persona_name,
                   b.scenario,
                   b.example_dialog
            FROM chats c
            LEFT JOIN bots b ON b.bot_id = c.bot_id
            LEFT JOIN personas p ON p.persona_id = c.persona_id
            WHERE c.chat_id = $1::text AND c.user_id = $2::uuid
            """,
            chat_id,
            user_id,
        )
        
        if not chat_data:
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Get bot persona - ensure it's not None
        bot_persona = chat_data["bot_persona"]
        if bot_persona is None:
            bot_persona = ""
        user_persona = chat_data["user_persona"]
        bot_name = chat_data["bot_name"]
        persona_name = chat_data["persona_name"] or "User"
        scenario = chat_data["scenario"]
        example_dialog = chat_data["example_dialog"]
        
        # Replace {{char}} and {{user}} tags in personas BEFORE sending to model
        # These tags should only be used internally, actual names should be sent to the model
        bot_persona = bot_persona.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
        if user_persona:
            user_persona = user_persona.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
        
        # Replace tags in example_dialog
        if example_dialog:
            example_dialog = example_dialog.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
        
        # Replace tags in scenario
        if scenario:
            scenario = scenario.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
        
        # Fetch active system prompt
        system_prompt_row = await conn.fetchrow(
            """
            SELECT content
            FROM system_prompts
            WHERE is_active = true
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        
        system_prompt = system_prompt_row["content"] if system_prompt_row else "You are a helpful AI assistant."
        # Replace {{char}} and {{user}} tags in system prompt BEFORE sending to model
        system_prompt = system_prompt.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
        
        # Check if this is the first user message (only greeting exists, or no messages)
        message_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM messages 
            WHERE chat_id = $1::text AND sender_type = 'user'
            """,
            chat_id
        )
        is_first_message = (message_count == 0)
        
        # Fetch active model
        model_row = await conn.fetchrow(
            """
            SELECT model_id, name, api_url, api_key, model_name, custom_prompt
            FROM models
            WHERE is_active = true
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        
        if not model_row:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No active model configured. Please configure a model in the admin dashboard.",
            )
        
        # Convert localhost to host.docker.internal for Docker containers
        # This allows accessing services running on the host machine
        api_url = model_row["api_url"].rstrip("/")
        if "localhost" in api_url or "127.0.0.1" in api_url:
            # Replace localhost/127.0.0.1 with host.docker.internal
            # This works on Docker Desktop (Windows/Mac) and Linux with extra_hosts
            api_url = api_url.replace("127.0.0.1", "host.docker.internal")
            api_url = api_url.replace("localhost", "host.docker.internal")
        
        # Ensure API URL includes the chat completions endpoint
        if not api_url.endswith("/chat/completions"):
            # If it's a base URL, append the chat completions endpoint
            if not api_url.endswith("/v1"):
                api_url = f"{api_url}/v1/chat/completions"
            else:
                api_url = f"{api_url}/chat/completions"
        
        # Fetch chat history
        # When excluding last bot message (reroll), only fetch selected messages to avoid non-selected attempts
        if exclude_last_bot_message:
            # For reroll: only get selected messages (to exclude non-selected reroll attempts)
            history_rows = await conn.fetch(
                """
                SELECT message_id,
                       sender_type AS sender,
                       content
                FROM messages
                WHERE chat_id = $1::text
                  AND (sender_type = 'user' OR (sender_type = 'bot' AND is_selected = true))
                ORDER BY created_at ASC, message_id ASC
                """,
                chat_id,
            )
        else:
            # For normal generation: get all messages
            history_rows = await conn.fetch(
                """
                SELECT message_id,
                       sender_type AS sender,
                       content
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at ASC, message_id ASC
                """,
                chat_id,
            )
        
        # Build chat history in OpenAI format
        chat_history = []
        for row in history_rows:
            role = "user" if row["sender"] == "user" else "assistant"
            chat_history.append({"role": role, "content": row["content"]})
        
        # If rerolling, exclude the last bot message from history (it's the one we're replacing)
        if exclude_last_bot_message and chat_history and chat_history[-1]["role"] == "assistant":
            chat_history = chat_history[:-1]
    
        # Replace {{char}} and {{user}} tags in custom_prompt if it exists
        custom_prompt = model_row["custom_prompt"]
        if custom_prompt:
            custom_prompt = custom_prompt.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
    
    # Prepare request to worker service
    worker_request = {
        "chat_history": chat_history,
        "bot_persona": bot_persona,
        "user_persona": user_persona,
        "system_prompt": system_prompt,
        "scenario": scenario if is_first_message else None,  # Only send scenario on first message
        "example_dialog": example_dialog,  # Always send example_dialog
        "api_config": {
            "api_url": api_url,
            "api_key": model_row["api_key"],
            "model_name": model_row["model_name"],
            "custom_prompt": custom_prompt,
        },
        "generation_settings": generation_settings,  # Pass through generation settings if provided
    }
    
    # Call worker service
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post(
                f"{WORKER_URL}/generate",
                json=worker_request,
            )
            response.raise_for_status()
            result = response.json()
            reply = result.get("reply")
            if not reply:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="API returned empty reply",
                )
            
            # Replace referencing tags: {{user}} -> persona_name, {{char}} -> bot_name
            reply = reply.replace("{{user}}", persona_name)
            reply = reply.replace("{{char}}", bot_name)
            
            return reply
    except httpx.HTTPStatusError as e:
        logger.error(f"Worker service error: {e.response.text}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Worker service error: {e.response.text}",
        )
    except httpx.TimeoutException as e:
        logger.error(f"Timeout contacting worker service: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Request timed out: {str(e)}",
        )
    except httpx.RequestError as e:
        logger.error(f"Failed to contact worker service: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Worker service unavailable: {str(e)}",
        )


@router.post(
    "/{chat_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    chat_id: str,
    payload: ChatMessageIn,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async with pool.acquire() as conn:
        # If commit_previous is True, commit any pending bot reply
        if payload.commit_previous:
            # Check if there's an uncommitted bot message (last message is bot, no user message after)
            last_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type, content
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            # If last message exists and is from bot, it's already committed (we always commit)
            # This is for future use if we implement true pending messages
        
        async with conn.transaction():
            chat_row = await conn.fetchrow(
                """
                SELECT c.chat_id,
                       c.title,
                       c.bot_id,
                       COALESCE(b.name, 'Unknown Bot') AS bot_name
                FROM chats c
                LEFT JOIN bots b ON b.bot_id = c.bot_id
                WHERE c.chat_id = $1::text
                """,
                chat_id,
            )
            if not chat_row:
                raise HTTPException(status_code=404, detail="Chat not found")

            bot_name = chat_row["bot_name"]

            # Insert user message
            await conn.execute(
                """
                INSERT INTO messages (chat_id, sender_type, content)
                VALUES ($1::text, 'user', $2)
                """,
                chat_id,
                message,
            )

            # Note: Generate bot reply outside transaction to avoid blocking
            pass
    
    # Prepare generation settings from payload
    gen_settings = None
    if payload.generation_settings:
        gen_settings = {
            "temperature": payload.generation_settings.temperature,
            "max_tokens": payload.generation_settings.max_tokens,
            "top_p": payload.generation_settings.top_p,
            "frequency_penalty": payload.generation_settings.frequency_penalty,
            "presence_penalty": payload.generation_settings.presence_penalty,
        }
        # Remove None values
        gen_settings = {k: v for k, v in gen_settings.items() if v is not None}
        if not gen_settings:  # If all values are None, set to None
            gen_settings = None
    
    # Generate bot reply (outside transaction to avoid blocking)
    # If generation fails, we need to remove the user message to allow retry
    user_message_id = None
    try:
        # Get the user message ID we just inserted
        async with pool.acquire() as conn:
            user_msg_row = await conn.fetchrow(
                """
                SELECT message_id
                FROM messages
                WHERE chat_id = $1::text AND sender_type = 'user'
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            if user_msg_row:
                user_message_id = user_msg_row["message_id"]
        
        bot_reply = await _generate_bot_reply(chat_id, message, pool, current_user["user_id"], generation_settings=gen_settings)
        
            # Insert bot reply and clean up non-selected reroll attempts
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO messages (chat_id, sender_type, content)
                VALUES ($1::text, 'bot', $2)
                """,
                chat_id,
                bot_reply,
            )
            
            # Delete all non-selected reroll attempts (keep only selected ones)
            await conn.execute(
                """
                DELETE FROM messages
                WHERE chat_id = $1::text
                  AND parent_message_id IS NOT NULL
                  AND parent_message_id != message_id
                  AND is_selected = false
                """,
                chat_id,
            )
            
            # Update last_used
            await conn.execute(
                "UPDATE chats SET last_used = NOW() WHERE chat_id = $1::text",
                chat_id,
            )
    except Exception as e:
        # If bot reply generation failed, remove the user message to allow clean retry
        if user_message_id:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM messages WHERE message_id = $1",
                    user_message_id,
                )
        # Re-raise the exception so the error is properly returned to the client
        raise

    # Re-fetch chat with full history
    chat = await _fetch_chat_detail(pool, chat_id, current_user["user_id"])
    if not chat:
        # Should not happen, but be defensive.
        raise HTTPException(status_code=500, detail="Chat disappeared unexpectedly")

    return ChatMessageResponse(chat=chat, bot_reply=bot_reply)


async def stream_bot_reply(
    chat_id: str,
    user_message: str,
    pool: asyncpg.Pool,
    user_message_id: int,
    user_id: UUID,
    generation_settings: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream bot reply and yield tokens as they arrive.
    Also saves the complete reply when done.
    """
    try:
        # Fetch chat details (same as _generate_bot_reply)
        async with pool.acquire() as conn:
            chat_data = await conn.fetchrow(
                """
                SELECT c.chat_id,
                       c.persona_id,
                       c.user_id,
                       b.persona AS bot_persona,
                       COALESCE(b.name, 'Unknown Bot') AS bot_name,
                       p.description AS user_persona,
                       p.name AS persona_name,
                       b.scenario,
                       b.example_dialog
                FROM chats c
                LEFT JOIN bots b ON b.bot_id = c.bot_id
                LEFT JOIN personas p ON p.persona_id = c.persona_id
                WHERE c.chat_id = $1::text AND c.user_id = $2::uuid
                """,
                chat_id,
                user_id,
            )
            
            if not chat_data:
                yield f"data: {json.dumps({'error': 'Chat not found'})}\n\n"
                return
            
            bot_persona = chat_data["bot_persona"]
            if bot_persona is None:
                bot_persona = ""
            user_persona = chat_data["user_persona"]
            bot_name = chat_data["bot_name"]
            persona_name = chat_data["persona_name"] or "User"
            scenario = chat_data["scenario"]
            example_dialog = chat_data["example_dialog"]
            
            # Replace {{char}} and {{user}} tags in personas BEFORE sending to model
            # These tags should only be used internally, actual names should be sent to the model
            bot_persona = bot_persona.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            if user_persona:
                user_persona = user_persona.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            
            # Replace tags in example_dialog
            if example_dialog:
                example_dialog = example_dialog.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            
            # Replace tags in scenario
            if scenario:
                scenario = scenario.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            
            # Fetch active system prompt
            system_prompt_row = await conn.fetchrow(
                """
                SELECT content
                FROM system_prompts
                WHERE is_active = true
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            system_prompt = system_prompt_row["content"] if system_prompt_row else "You are a helpful AI assistant."
            # Replace {{char}} and {{user}} tags in system prompt BEFORE sending to model
            system_prompt = system_prompt.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            
            # Check if this is the first user message (only greeting exists, or no messages)
            message_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM messages 
                WHERE chat_id = $1::text AND sender_type = 'user'
                """,
                chat_id
            )
            is_first_message = (message_count == 0)
            
            # Fetch active model
            model_row = await conn.fetchrow(
                """
                SELECT model_id, name, api_url, api_key, model_name, custom_prompt
                FROM models
                WHERE is_active = true
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            
            if not model_row:
                yield f"data: {json.dumps({'error': 'No active model configured'})}\n\n"
                return
            
            # Ensure API URL includes the chat completions endpoint
            api_url = model_row["api_url"].rstrip("/")
            if "localhost" in api_url or "127.0.0.1" in api_url:
                api_url = api_url.replace("127.0.0.1", "host.docker.internal")
                api_url = api_url.replace("localhost", "host.docker.internal")
            
            if not api_url.endswith("/chat/completions"):
                if not api_url.endswith("/v1"):
                    api_url = f"{api_url}/v1/chat/completions"
                else:
                    api_url = f"{api_url}/chat/completions"
            
            # Fetch chat history
            history_rows = await conn.fetch(
                """
                SELECT message_id,
                       sender_type AS sender,
                       content
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at ASC, message_id ASC
                """,
                chat_id,
            )
            
            # Build chat history
            chat_history = []
            for row in history_rows:
                role = "user" if row["sender"] == "user" else "assistant"
                chat_history.append({"role": role, "content": row["content"]})
        
            # Replace {{char}} and {{user}} tags in custom_prompt if it exists
            custom_prompt = model_row["custom_prompt"]
            if custom_prompt:
                custom_prompt = custom_prompt.replace("{{char}}", bot_name).replace("{{user}}", persona_name)
            else:
                custom_prompt = None
        
            # Prepare request to worker service
            worker_request = {
                "chat_history": chat_history,
                "bot_persona": bot_persona,
                "user_persona": user_persona,
                "system_prompt": system_prompt,
                "scenario": scenario if is_first_message else None,  # Only send scenario on first message
                "example_dialog": example_dialog,  # Always send example_dialog
                "api_config": {
                    "api_url": api_url,
                    "api_key": model_row["api_key"],
                    "model_name": model_row["model_name"],
                    "custom_prompt": custom_prompt,
                },
                "generation_settings": generation_settings,
            }
        
        # Stream from worker service
        WORKER_URL = os.getenv("WORKER_URL", "http://orp-worker:8081")
        accumulated_reply = ""
        cancelled = False
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{WORKER_URL}/generate/stream",
                    json=worker_request,
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        yield f"data: {json.dumps({'error': f'Worker service error: {error_text.decode()}'})}\n\n"
                        return
                    
                    async for line in response.aiter_lines():
                        # Check for cancellation before processing each line
                        if chat_id in _active_streams and user_message_id in _active_streams[chat_id]:
                            cancel_event = _active_streams[chat_id][user_message_id]
                            if isinstance(cancel_event, asyncio.Event) and cancel_event.is_set():
                                cancelled = True
                                yield f"data: {json.dumps({'cancelled': True})}\n\n"
                                break
                        
                        if not line.strip():
                            continue
                        
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                
                                if "error" in data:
                                    yield f"data: {json.dumps(data)}\n\n"
                                    return
                                
                                if "done" in data:
                                    break
                                
                                if "content" in data:
                                    content = data["content"]
                                    # Replace referencing tags
                                    content = content.replace("{{user}}", persona_name)
                                    content = content.replace("{{char}}", bot_name)
                                    accumulated_reply += content
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            except json.JSONDecodeError:
                                continue
        except asyncio.CancelledError:
            cancelled = True
            yield f"data: {json.dumps({'cancelled': True})}\n\n"
        except Exception as e:
            if not cancelled:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        # Save the complete bot reply (only if not cancelled)
        if accumulated_reply and not cancelled:
            async with pool.acquire() as conn2:
                await conn2.execute(
                    """
                    INSERT INTO messages (chat_id, sender_type, content)
                    VALUES ($1::text, 'bot', $2)
                    """,
                    chat_id,
                    accumulated_reply,
                )
                
                # Delete all non-selected reroll attempts (keep only selected ones)
                await conn2.execute(
                    """
                    DELETE FROM messages
                    WHERE chat_id = $1::text
                      AND parent_message_id IS NOT NULL
                      AND parent_message_id != message_id
                      AND is_selected = false
                    """,
                    chat_id,
                )
                
                await conn2.execute(
                    "UPDATE chats SET last_used = NOW() WHERE chat_id = $1::text",
                    chat_id,
                )
            
            yield f"data: {json.dumps({'done': True})}\n\n"
        elif cancelled:
            # Delete user message if cancelled
            async with pool.acquire() as conn2:
                await conn2.execute(
                    "DELETE FROM messages WHERE message_id = $1",
                    user_message_id,
                )
            yield f"data: {json.dumps({'cancelled': True, 'done': True})}\n\n"
        else:
            yield f"data: {json.dumps({'error': 'No content received'})}\n\n"
        
        # Clean up active stream tracking
        if chat_id in _active_streams and user_message_id in _active_streams[chat_id]:
            del _active_streams[chat_id][user_message_id]
            if not _active_streams[chat_id]:
                del _active_streams[chat_id]
            
    except Exception as e:
        logger.error(f"Error streaming bot reply: {e}", exc_info=True)
        # Delete user message on error
        if user_message_id:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM messages WHERE message_id = $1",
                    user_message_id,
                )
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@router.post("/{chat_id}/messages/stream")
async def send_message_stream(
    chat_id: str,
    payload: ChatMessageIn,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Send a message and stream the bot reply as Server-Sent Events.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async with pool.acquire() as conn:
        async with conn.transaction():
            chat_row = await conn.fetchrow(
                """
                SELECT c.chat_id,
                       c.title,
                       c.bot_id,
                       COALESCE(b.name, 'Unknown Bot') AS bot_name
                FROM chats c
                LEFT JOIN bots b ON b.bot_id = c.bot_id
                WHERE c.chat_id = $1::text
                """,
                chat_id,
            )
            if not chat_row:
                raise HTTPException(status_code=404, detail="Chat not found")

            # Insert user message
            await conn.execute(
                """
                INSERT INTO messages (chat_id, sender_type, content)
                VALUES ($1::text, 'user', $2)
                RETURNING message_id
                """,
                chat_id,
                message,
            )
            
            # Get the user message ID
            user_msg_row = await conn.fetchrow(
                """
                SELECT message_id
                FROM messages
                WHERE chat_id = $1::text AND sender_type = 'user'
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            user_message_id = user_msg_row["message_id"] if user_msg_row else None
    
    # Prepare generation settings
    gen_settings = None
    if payload.generation_settings:
        gen_settings = {
            "temperature": payload.generation_settings.temperature,
            "max_tokens": payload.generation_settings.max_tokens,
            "top_p": payload.generation_settings.top_p,
            "frequency_penalty": payload.generation_settings.frequency_penalty,
            "presence_penalty": payload.generation_settings.presence_penalty,
        }
        gen_settings = {k: v for k, v in gen_settings.items() if v is not None}
        if not gen_settings:
            gen_settings = None
    
    # Create a cancellation event for this stream and track it
    cancel_event = asyncio.Event()
    if chat_id not in _active_streams:
        _active_streams[chat_id] = {}
    _active_streams[chat_id][user_message_id] = cancel_event
    
    async def stream_with_cancellation():
        try:
            async for chunk in stream_bot_reply(chat_id, message, pool, user_message_id, current_user["user_id"], gen_settings):
                # Check cancellation before yielding each chunk
                if cancel_event.is_set():
                    yield f"data: {json.dumps({'cancelled': True, 'done': True})}\n\n"
                    break
                yield chunk
        finally:
            # Clean up tracking
            if chat_id in _active_streams and user_message_id in _active_streams[chat_id]:
                del _active_streams[chat_id][user_message_id]
                if not _active_streams[chat_id]:
                    del _active_streams[chat_id]
    
    return StreamingResponse(
        stream_with_cancellation(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post(
    "/{chat_id}/reroll",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_200_OK,
)
async def reroll_last_message(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Reroll the last bot message by generating a new reply to the last user message.
    Updates the last bot message in the database.
    """
    async with pool.acquire() as conn:
        # Verify chat belongs to user
        chat_owner = await conn.fetchval(
            "SELECT user_id FROM chats WHERE chat_id = $1::text",
            chat_id
        )
        if str(chat_owner) != str(current_user["user_id"]):
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Get the last SELECTED bot message and last user message
        # Find the selected bot message: is_selected = true, or if NULL check if it's the only bot message
        # First try to find a selected message
        last_bot_msg = await conn.fetchrow(
            """
            SELECT message_id, sender_type, content, is_selected, parent_message_id, attempt_number
            FROM messages
            WHERE chat_id = $1::text
              AND sender_type = 'bot'
              AND is_selected = true
            ORDER BY created_at DESC, message_id DESC
            LIMIT 1
            """,
            chat_id,
        )
        
        # If no selected message found, get the most recent bot message (for backward compatibility)
        if not last_bot_msg:
            last_bot_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type, content, is_selected, parent_message_id, attempt_number
                FROM messages
                WHERE chat_id = $1::text
                  AND sender_type = 'bot'
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
        
        last_user_msg = await conn.fetchrow(
            """
            SELECT message_id, sender_type, content
            FROM messages
            WHERE chat_id = $1::text
              AND sender_type = 'user'
            ORDER BY created_at DESC, message_id DESC
            LIMIT 1
            """,
            chat_id,
        )
        
        if not last_bot_msg or not last_user_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reroll: need at least one user message and one bot reply",
            )
        
        if last_bot_msg["sender_type"] != "bot" or last_user_msg["sender_type"] != "user":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reroll: last message must be from bot, preceded by user message",
            )
        
        user_message = last_user_msg["content"]
        bot_message_id = last_bot_msg["message_id"]
        
        # Get the parent message ID (original message if this is a reroll attempt)
        parent_msg = await conn.fetchrow(
            """
            SELECT parent_message_id, attempt_number, is_selected
            FROM messages
            WHERE message_id = $1
            """,
            bot_message_id,
        )
        
        # Determine parent message ID and next attempt number
        # If parent_message_id is NULL or equals message_id, this IS the parent
        if parent_msg and parent_msg["parent_message_id"] and parent_msg["parent_message_id"] != bot_message_id:
            # This is already a reroll attempt, use the same parent
            parent_message_id = parent_msg["parent_message_id"]
            # Get max attempt number for this parent
            # Parent has attempt_number = 0, rerolls have 1, 2, 3...
            max_attempt_row = await conn.fetchrow(
                """
                SELECT COALESCE(MAX(attempt_number), 0) as max_attempt
                FROM messages
                WHERE (
                    (parent_message_id = $1 AND parent_message_id != message_id)
                    OR (message_id = $1 AND (parent_message_id IS NULL OR parent_message_id = message_id))
                )
                  AND chat_id = $2::text
                """,
                parent_message_id,
                chat_id,
            )
            max_attempt = max_attempt_row["max_attempt"] if max_attempt_row else 0
            next_attempt = max_attempt + 1
        else:
            # This is the original message, make it the parent
            parent_message_id = bot_message_id
            next_attempt = 1
            
            # Mark original message as not selected, set its attempt_number to 0, and parent to itself
            await conn.execute(
                """
                UPDATE messages
                SET is_selected = false, attempt_number = 0, parent_message_id = $1
                WHERE message_id = $1
                """,
                bot_message_id,
            )
        
        # Generate new bot reply (reroll uses default generation settings)
        # Exclude the last bot message from history since we're replacing it
        bot_reply = await _generate_bot_reply(chat_id, user_message, pool, current_user["user_id"], generation_settings=None, exclude_last_bot_message=True)
        
        # Create new reroll attempt
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO messages (chat_id, sender_type, content, parent_message_id, attempt_number, is_selected)
                VALUES ($1::text, 'bot', $2, $3, $4, true)
                """,
                chat_id,
                bot_reply,
                parent_message_id,
                next_attempt,
            )
            
            # Mark all other attempts (including parent) as not selected
            # The newly created attempt is already marked as selected, so we exclude it
            # Parent has parent_message_id = NULL or = message_id, rerolls have parent_message_id = parent_message_id
            await conn.execute(
                """
                UPDATE messages
                SET is_selected = false
                WHERE (
                    (parent_message_id = $1 AND parent_message_id != message_id AND attempt_number != $2)
                    OR (message_id = $1 AND (parent_message_id IS NULL OR parent_message_id = message_id) AND attempt_number != $2)
                )
                  AND chat_id = $3::text
                """,
                parent_message_id,
                next_attempt,
                chat_id,
            )
            
            # Update last_used
            await conn.execute(
                "UPDATE chats SET last_used = NOW() WHERE chat_id = $1::text",
                chat_id,
            )
    
    # Re-fetch chat with full history
    chat = await _fetch_chat_detail(pool, chat_id, current_user["user_id"])
    if not chat:
        raise HTTPException(status_code=500, detail="Chat disappeared unexpectedly")
    
    # Get the newly created message
    async with pool.acquire() as conn2:
        new_msg = await conn2.fetchrow(
            """
            SELECT content FROM messages
            WHERE chat_id = $1::text AND parent_message_id = $2 AND attempt_number = $3
            """,
            chat_id,
            parent_message_id,
            next_attempt,
        )
    
    return ChatMessageResponse(chat=chat, bot_reply=new_msg["content"] if new_msg else "")


@router.delete("/{chat_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    chat_id: str,
    message_id: int,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Delete a user message and all subsequent messages (both user and bot).
    Only user messages can be deleted.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Verify chat belongs to user
            chat_owner = await conn.fetchval(
                "SELECT user_id FROM chats WHERE chat_id = $1::text",
                chat_id
            )
            if str(chat_owner) != str(current_user["user_id"]):
                raise HTTPException(status_code=404, detail="Chat not found")
            
            # Check if message exists and get its details
            msg_row = await conn.fetchrow(
                """
                SELECT message_id, sender_type, created_at
                FROM messages
                WHERE message_id = $1 AND chat_id = $2::text
                """,
                message_id,
                chat_id,
            )
            
            if not msg_row:
                raise HTTPException(status_code=404, detail="Message not found")
            
            # Check if this is the greeting message (first bot message)
            first_bot_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at ASC, message_id ASC
                LIMIT 1
                """,
                chat_id,
            )
            is_greeting = (first_bot_msg and 
                          first_bot_msg["message_id"] == message_id and 
                          first_bot_msg["sender_type"] == "bot")
            
            if is_greeting:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the initial greeting message",
                )
            
            # Only allow deletion of user messages
            if msg_row["sender_type"] != "user":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only user messages can be deleted",
                )
            
            # Delete the message and all subsequent messages (by created_at and message_id)
            # Also delete all reroll attempts for deleted messages
            result = await conn.execute(
                """
                DELETE FROM messages
                WHERE chat_id = $1::text
                  AND (
                    created_at > (SELECT created_at FROM messages WHERE message_id = $2)
                    OR (created_at = (SELECT created_at FROM messages WHERE message_id = $2)
                        AND message_id >= $2)
                    OR parent_message_id IN (
                        SELECT message_id FROM messages
                        WHERE chat_id = $1::text
                          AND (
                            created_at > (SELECT created_at FROM messages WHERE message_id = $2)
                            OR (created_at = (SELECT created_at FROM messages WHERE message_id = $2)
                                AND message_id >= $2)
                          )
                    )
                  )
                """,
                chat_id,
                message_id,
            )
            
            # After deleting a user message, if the last message is now a bot message,
            # make it rerollable by resetting its parent/attempt fields
            last_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type, parent_message_id
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            
            if last_msg and last_msg["sender_type"] == "bot":
                last_bot_msg_id = last_msg["message_id"]
                # Delete any existing reroll attempts for this message first
                await conn.execute(
                    """
                    DELETE FROM messages
                    WHERE parent_message_id = $1
                      AND message_id != $1
                    """,
                    last_bot_msg_id,
                )
                
                # Reset reroll fields to make it rerollable (set parent_message_id to NULL)
                await conn.execute(
                    """
                    UPDATE messages
                    SET parent_message_id = NULL, attempt_number = 0, is_selected = true
                    WHERE message_id = $1
                    """,
                    last_bot_msg_id,
                )
            
            # Update last_used
            await conn.execute(
                "UPDATE chats SET last_used = NOW() WHERE chat_id = $1::text",
                chat_id,
            )
    
    return None


@router.put("/{chat_id}/messages/{message_id}", response_model=MessageOut)
async def update_message(
    chat_id: str,
    message_id: int,
    payload: MessageUpdate,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Update a message. Only messages within 3 steps back from the latest message can be edited.
    """
    new_content = payload.content.strip()
    if not new_content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Verify chat belongs to user
            chat_owner = await conn.fetchval(
                "SELECT user_id FROM chats WHERE chat_id = $1::text",
                chat_id
            )
            if str(chat_owner) != str(current_user["user_id"]):
                raise HTTPException(status_code=404, detail="Chat not found")
            
            # Get the message to edit
            msg_row = await conn.fetchrow(
                """
                SELECT message_id, sender_type, created_at
                FROM messages
                WHERE message_id = $1 AND chat_id = $2::text
                """,
                message_id,
                chat_id,
            )
            
            if not msg_row:
                raise HTTPException(status_code=404, detail="Message not found")
            
            # Check if this is the greeting message (first bot message)
            first_bot_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at ASC, message_id ASC
                LIMIT 1
                """,
                chat_id,
            )
            is_greeting = (first_bot_msg and 
                          first_bot_msg["message_id"] == message_id and 
                          first_bot_msg["sender_type"] == "bot")
            
            if is_greeting:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot edit the initial greeting message",
                )
            
            # Get the latest message in the chat
            latest_msg = await conn.fetchrow(
                """
                SELECT message_id, created_at
                FROM messages
                WHERE chat_id = $1::text
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            
            if not latest_msg:
                raise HTTPException(status_code=404, detail="No messages found in chat")
            
            # Count how many messages are after the one being edited
            messages_after = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE chat_id = $1::text
                  AND (
                    created_at > (SELECT created_at FROM messages WHERE message_id = $2)
                    OR (created_at = (SELECT created_at FROM messages WHERE message_id = $2)
                        AND message_id > $2)
                  )
                """,
                chat_id,
                message_id,
            )
            
            # Only allow editing if message is within 3 steps back
            if messages_after > 3:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Message is too far back in history. Can only edit messages within 3 steps back. This message is {messages_after} steps back.",
                )
            
            # Update the message
            await conn.execute(
                """
                UPDATE messages
                SET content = $1
                WHERE message_id = $2
                """,
                new_content,
                message_id,
            )
            
            # Update last_used
            await conn.execute(
                "UPDATE chats SET last_used = NOW() WHERE chat_id = $1::text",
                chat_id,
            )
            
            # Fetch updated message
            updated_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type AS sender, content, created_at
                FROM messages
                WHERE message_id = $1
                """,
                message_id,
            )
    
    return MessageOut(
        message_id=updated_msg["message_id"],
        sender=updated_msg["sender"],
        content=updated_msg["content"],
        created_at=updated_msg["created_at"],
    )


@router.post("/{chat_id}/messages/{message_id}/select-attempt/{attempt_number}", response_model=MessageOut)
async def select_reroll_attempt(
    chat_id: str,
    message_id: int,
    attempt_number: int,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Select a specific reroll attempt. This marks it as selected and unmarks others.
    The message_id can be either the parent message or any attempt - we'll find the parent.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Verify chat belongs to user
            chat_owner = await conn.fetchval(
                "SELECT user_id FROM chats WHERE chat_id = $1::text",
                chat_id
            )
            if str(chat_owner) != str(current_user["user_id"]):
                raise HTTPException(status_code=404, detail="Chat not found")
            
            # Verify the message exists and get parent
            msg = await conn.fetchrow(
                """
                SELECT parent_message_id, attempt_number
                FROM messages
                WHERE message_id = $1 AND chat_id = $2::text
                """,
                message_id,
                chat_id,
            )
            
            if not msg:
                raise HTTPException(status_code=404, detail="Message not found")
            
            # Determine parent message ID
            # If parent_message_id is NULL or equals message_id, this IS the parent
            if msg["parent_message_id"] is None or msg["parent_message_id"] == message_id:
                parent_message_id = message_id
            else:
                parent_message_id = msg["parent_message_id"]
            
            # Find the attempt to select (attempt_number 0 is the parent, others are rerolls)
            if attempt_number == 0:
                # Select the parent message (parent has parent_message_id = message_id or NULL)
                target_msg = await conn.fetchrow(
                    """
                    SELECT message_id FROM messages
                    WHERE message_id = $1 
                      AND chat_id = $2::text::text
                      AND (parent_message_id IS NULL OR parent_message_id = message_id)
                    """,
                    parent_message_id,
                    chat_id,
                )
            else:
                # Select a reroll attempt (rerolls have parent_message_id = parent_message_id and parent_message_id != message_id)
                target_msg = await conn.fetchrow(
                    """
                    SELECT message_id FROM messages
                    WHERE parent_message_id = $1
                      AND parent_message_id != message_id
                      AND attempt_number = $2
                      AND chat_id = $3::text
                    """,
                    parent_message_id,
                    attempt_number,
                    chat_id,
                )
            
            if not target_msg:
                raise HTTPException(status_code=404, detail="Reroll attempt not found")
            
            # Mark all attempts (including parent) as not selected
            # Parent has parent_message_id = NULL or = message_id, rerolls have parent_message_id = parent_message_id
            await conn.execute(
                """
                UPDATE messages
                SET is_selected = false
                WHERE (
                    (parent_message_id = $1 AND parent_message_id != message_id)
                    OR (message_id = $1 AND (parent_message_id IS NULL OR parent_message_id = message_id))
                )
                  AND chat_id = $2::text
                """,
                parent_message_id,
                chat_id,
            )
            
            # Mark selected attempt as selected
            await conn.execute(
                """
                UPDATE messages
                SET is_selected = true
                WHERE message_id = $1
                """,
                target_msg["message_id"],
            )
            
            # Fetch updated message
            updated_msg = await conn.fetchrow(
                """
                SELECT message_id, sender_type AS sender, content, created_at,
                       parent_message_id, attempt_number, is_selected
                FROM messages
                WHERE message_id = $1
                """,
                target_msg["message_id"],
            )
            
            # Get total attempts (parent + all rerolls)
            total_attempts = await conn.fetchval(
                """
                SELECT COUNT(*) FROM messages
                WHERE (parent_message_id = $1 OR message_id = $1)
                  AND chat_id = $2::text
                """,
                parent_message_id,
                chat_id,
            )
    
    return MessageOut(
        message_id=updated_msg["message_id"],
        sender=updated_msg["sender"],
        content=updated_msg["content"],
        created_at=updated_msg["created_at"],
        parent_message_id=updated_msg["parent_message_id"],
        attempt_number=updated_msg["attempt_number"],
        is_selected=updated_msg["is_selected"],
        total_attempts=total_attempts,
    )


@router.get("/{chat_id}/messages/{message_id}/attempts", response_model=List[MessageOut])
async def get_reroll_attempts(
    chat_id: str,
    message_id: int,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Get all reroll attempts for a message.
    """
    async with pool.acquire() as conn:
        # Verify chat belongs to user
        chat_owner = await conn.fetchval(
            "SELECT user_id FROM chats WHERE chat_id = $1::text",
            chat_id
        )
        if str(chat_owner) != str(current_user["user_id"]):
            raise HTTPException(status_code=404, detail="Chat not found")
        
        # Get parent message ID
        msg = await conn.fetchrow(
            """
            SELECT parent_message_id FROM messages
            WHERE message_id = $1 AND chat_id = $2::text
            """,
            message_id,
            chat_id,
        )
        
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Determine parent: if parent_message_id is NULL or equals message_id, this IS the parent
        if msg["parent_message_id"] is None or msg["parent_message_id"] == message_id:
            parent_message_id = message_id
        else:
            parent_message_id = msg["parent_message_id"]
        
        # Get all attempts (parent has parent_message_id = NULL or = message_id, rerolls have parent_message_id = parent_message_id)
        attempts = await conn.fetch(
            """
            SELECT message_id, sender_type AS sender, content, created_at,
                   parent_message_id, attempt_number, is_selected
            FROM messages
            WHERE (
                (parent_message_id = $1 AND parent_message_id != message_id)
                OR (message_id = $1 AND (parent_message_id IS NULL OR parent_message_id = message_id))
            )
              AND chat_id = $2::text
            ORDER BY attempt_number ASC
            """,
            parent_message_id,
            chat_id,
        )
        
        total_attempts = len(attempts)
        
        return [
            MessageOut(
                message_id=row["message_id"],
                sender=row["sender"],
                content=row["content"],
                created_at=row["created_at"],
                parent_message_id=row["parent_message_id"],
                attempt_number=row["attempt_number"],
                is_selected=row["is_selected"],
                total_attempts=total_attempts,
            )
            for row in attempts
        ]


@router.post("/{chat_id}/stream/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_streaming(
    chat_id: str,
    current_user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Cancel any active streaming request for this chat.
    """
    # Verify chat belongs to user
    async with pool.acquire() as conn:
        chat_owner = await conn.fetchval(
            "SELECT user_id FROM chats WHERE chat_id = $1::text",
            chat_id
        )
        if str(chat_owner) != str(current_user["user_id"]):
            raise HTTPException(status_code=404, detail="Chat not found")
    
    if chat_id in _active_streams:
        for user_message_id, cancel_event in _active_streams[chat_id].items():
            if isinstance(cancel_event, asyncio.Event):
                cancel_event.set()
        
        # Clean up the user message if streaming was cancelled
        async with pool.acquire() as conn:
            # Get the last user message
            last_user_msg = await conn.fetchrow(
                """
                SELECT message_id FROM messages
                WHERE chat_id = $1::text AND sender_type = 'user'
                ORDER BY created_at DESC, message_id DESC
                LIMIT 1
                """,
                chat_id,
            )
            
            if last_user_msg:
                # Delete the user message if it doesn't have a bot reply yet
                bot_reply_exists = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM messages
                        WHERE chat_id = $1::text
                          AND sender_type = 'bot'
                          AND created_at > (SELECT created_at FROM messages WHERE message_id = $2)
                    )
                    """,
                    chat_id,
                    last_user_msg["message_id"],
                )
                
                if not bot_reply_exists:
                    await conn.execute(
                        "DELETE FROM messages WHERE message_id = $1",
                        last_user_msg["message_id"],
                    )
        
        del _active_streams[chat_id]
    
    return None
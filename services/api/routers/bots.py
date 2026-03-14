# services/api/app/routers/bots.py

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
import asyncpg

from app.db import get_pool
from app.schemas import BotCreate, BotUpdate, BotOut
from app.utils import save_profile_picture, delete_profile_picture

logger = logging.getLogger(__name__)
router = APIRouter()


async def _fetch_bot(pool: asyncpg.Pool, bot_id: int) -> BotOut | None:
    row = await pool.fetchrow(
        """
        SELECT b.bot_id,
               b.title,
               b.name,
               b.description,
               b.persona,
               b.avatar_url,
               b.scenario,
               b.greeting,
               b.example_dialog,
               COALESCE(
                   array_agg(t.name ORDER BY t.name)
                   FILTER (WHERE t.name IS NOT NULL),
                   '{}'
               ) AS tags
        FROM bots b
        LEFT JOIN bot_tags bt ON b.bot_id = bt.bot_id
        LEFT JOIN tags t ON bt.tag_id = t.tag_id
        WHERE b.bot_id = $1
        GROUP BY b.bot_id, b.title, b.name, b.description, b.persona, b.avatar_url, b.scenario, b.greeting, b.example_dialog
        """,
        bot_id,
    )
    if not row:
        return None

    return BotOut(
        bot_id=row["bot_id"],
        title=row["title"],
        name=row["name"],
        description=row["description"],
        persona=row["persona"],
        tags=list(row["tags"]),
        avatar_url=row["avatar_url"],
        scenario=row["scenario"],
        greeting=row["greeting"],
        example_dialog=row["example_dialog"],
    )


@router.get("", response_model=List[BotOut])
async def list_bots(pool: asyncpg.Pool = Depends(get_pool)):
    try:
        logger.info("Fetching list of bots")
        rows = await pool.fetch(
            """
            SELECT b.bot_id,
                   b.title,
                   b.name,
                   b.description,
                   b.persona,
                   b.avatar_url,
                   b.scenario,
                   b.greeting,
                   b.example_dialog,
                   COALESCE(
                       array_agg(t.name ORDER BY t.name)
                       FILTER (WHERE t.name IS NOT NULL),
                       '{}'
                   ) AS tags
            FROM bots b
            LEFT JOIN bot_tags bt ON b.bot_id = bt.bot_id
            LEFT JOIN tags t ON bt.tag_id = t.tag_id
            GROUP BY b.bot_id, b.title, b.name, b.description, b.persona, b.avatar_url, b.scenario, b.greeting, b.example_dialog
            ORDER BY b.bot_id
            """
        )

        result = [
            BotOut(
                bot_id=row["bot_id"],
                title=row["title"],
                name=row["name"],
                description=row["description"],
                persona=row["persona"],
                tags=list(row["tags"]),
                avatar_url=row["avatar_url"],
                scenario=row["scenario"],
                greeting=row["greeting"],
                example_dialog=row["example_dialog"],
            )
            for row in rows
        ]
        logger.info(f"Successfully fetched {len(result)} bots")
        return result
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error listing bots: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error listing bots: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(bot: BotCreate, pool: asyncpg.Pool = Depends(get_pool)):
    """
    Create a new bot in the `bots` table and attach tags via `tags` + `bot_tags`.

    `creator_id` is set to NULL for now; you can wire it to your auth later.
    """
    try:
        logger.info(f"Creating bot: title={bot.title}, name={bot.name}")
        async with pool.acquire() as conn:
            async with conn.transaction():
                bot_row = await conn.fetchrow(
                    """
                    INSERT INTO bots (creator_id, title, name, description, persona, avatar_url, scenario, greeting, example_dialog)
                    VALUES (NULL, $1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING bot_id, title, name, description, persona, avatar_url, scenario, greeting, example_dialog
                    """,
                    bot.title,
                    bot.name,
                    bot.description,
                    bot.persona,
                    bot.avatar_url,
                    bot.scenario,
                    bot.greeting,
                    bot.example_dialog,
                )
                bot_id = bot_row["bot_id"]
                logger.info(f"Bot created with ID: {bot_id}")

                # Insert tags and bot_tags
                for tag_name in bot.tags:
                    tag_row = await conn.fetchrow(
                        """
                        INSERT INTO tags (name)
                        VALUES ($1)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING tag_id
                        """,
                        tag_name,
                    )
                    tag_id = tag_row["tag_id"]
                    await conn.execute(
                        """
                        INSERT INTO bot_tags (bot_id, tag_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                        """,
                        bot_id,
                        tag_id,
                    )

        # Re-fetch with tags aggregated
        result = await _fetch_bot(pool, bot_id)
        if result is None:
            logger.error(f"Failed to fetch created bot with ID: {bot_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Bot was created but could not be retrieved",
            )
        return result
    except asyncpg.PostgresError as e:
        logger.error(f"PostgreSQL error creating bot: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error creating bot: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    bot = await _fetch_bot(pool, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.put("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: int,
    update: BotUpdate,
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Ensure bot exists
            exists = await conn.fetchval(
                "SELECT 1 FROM bots WHERE bot_id = $1", bot_id
            )
            if not exists:
                raise HTTPException(status_code=404, detail="Bot not found")

            # Update core fields
            if update.title is not None:
                await conn.execute(
                    "UPDATE bots SET title = $1 WHERE bot_id = $2",
                    update.title,
                    bot_id,
                )
            if update.name is not None:
                await conn.execute(
                    "UPDATE bots SET name = $1 WHERE bot_id = $2",
                    update.name,
                    bot_id,
                )
            if update.description is not None:
                await conn.execute(
                    "UPDATE bots SET description = $1 WHERE bot_id = $2",
                    update.description,
                    bot_id,
                )
            if update.persona is not None:
                await conn.execute(
                    "UPDATE bots SET persona = $1 WHERE bot_id = $2",
                    update.persona,
                    bot_id,
                )
            if update.avatar_url is not None:
                await conn.execute(
                    "UPDATE bots SET avatar_url = $1 WHERE bot_id = $2",
                    update.avatar_url,
                    bot_id,
                )
            if update.scenario is not None:
                await conn.execute(
                    "UPDATE bots SET scenario = $1 WHERE bot_id = $2",
                    update.scenario,
                    bot_id,
                )
            if update.greeting is not None:
                await conn.execute(
                    "UPDATE bots SET greeting = $1 WHERE bot_id = $2",
                    update.greeting,
                    bot_id,
                )
            if update.example_dialog is not None:
                await conn.execute(
                    "UPDATE bots SET example_dialog = $1 WHERE bot_id = $2",
                    update.example_dialog,
                    bot_id,
                )

            # Update tags if provided
            if update.tags is not None:
                # Clear existing tags
                await conn.execute(
                    "DELETE FROM bot_tags WHERE bot_id = $1", bot_id
                )

                # Re-insert
                for tag_name in update.tags:
                    tag_row = await conn.fetchrow(
                        """
                        INSERT INTO tags (name)
                        VALUES ($1)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING tag_id
                        """,
                        tag_name,
                    )
                    tag_id = tag_row["tag_id"]
                    await conn.execute(
                        """
                        INSERT INTO bot_tags (bot_id, tag_id)
                        VALUES ($1, $2)
                        """,
                        bot_id,
                        tag_id,
                    )

    return await _fetch_bot(pool, bot_id)


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    # Get avatar_url before deleting
    bot_row = await pool.fetchrow(
        "SELECT avatar_url FROM bots WHERE bot_id = $1", bot_id
    )
    
    result = await pool.execute(
        "DELETE FROM bots WHERE bot_id = $1", bot_id
    )
    # result is like "DELETE 1"
    if result.split()[-1] == "0":
        raise HTTPException(status_code=404, detail="Bot not found")
    
    # Delete profile picture if it exists
    if bot_row and bot_row["avatar_url"]:
        delete_profile_picture(bot_row["avatar_url"])
    
    return None


@router.post("/{bot_id}/avatar", response_model=BotOut)
async def upload_bot_avatar(
    bot_id: int,
    file: UploadFile = File(...),
    pool: asyncpg.Pool = Depends(get_pool)
):
    """Upload a profile picture for a bot."""
    try:
        # Check if bot exists
        bot = await _fetch_bot(pool, bot_id)
        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")
        
        # Delete old avatar if it exists
        if bot.avatar_url:
            delete_profile_picture(bot.avatar_url)
        
        # Save new avatar
        avatar_url = await save_profile_picture(file, "bots", bot_id)
        
        # Update bot in database
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE bots SET avatar_url = $1 WHERE bot_id = $2",
                avatar_url,
                bot_id
            )
        
        # Return updated bot
        return await _fetch_bot(pool, bot_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading bot avatar: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading avatar: {str(e)}"
        )

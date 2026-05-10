# services/api/app/utils.py

import uuid
import base64
import os
from pathlib import Path
from typing import Optional
from fastapi import UploadFile, HTTPException, status
from PIL import Image
import logging

logger = logging.getLogger(__name__)


def generate_short_uuid() -> str:
    """
    Generate a short UUID using base64url encoding.
    Returns a 22-character URL-safe string.
    """
    # Generate a UUID4
    uuid_bytes = uuid.uuid4().bytes
    
    # Encode to base64
    encoded = base64.b64encode(uuid_bytes).decode('ascii')
    
    # Make it URL-safe: replace + with -, / with _, and remove padding
    encoded = encoded.replace('+', '-').replace('/', '_').rstrip('=')
    
    # Return the first 22 characters (which is the standard length for base64url UUID)
    return encoded[:22]


# Allowed image MIME types
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp"
}

# Maximum file size: 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


def get_uploads_dir() -> Path:
    """Get the uploads directory path, creating it if it doesn't exist."""
    uploads_dir = Path("/app/warehouse/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return uploads_dir


async def save_profile_picture(
    file: UploadFile,
    entity_type: str,  # "bot" or "persona"
    entity_id: int
) -> str:
    """
    Save an uploaded profile picture and return the URL path.
    
    Args:
        file: The uploaded file
        entity_type: "bot" or "persona"
        entity_id: The ID of the bot or persona
    
    Returns:
        The URL path to the saved file (e.g., "/uploads/bots/123_abc123.jpg")
    """
    # Validate file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )
    
    # Read file content
    content = await file.read()
    
    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024 * 1024):.1f}MB"
        )
    
    # Validate it's actually an image by trying to open it
    try:
        from io import BytesIO
        img = Image.open(BytesIO(content))
        img.verify()  # Verify it's a valid image (this closes the image)
        # Reopen for format detection (verify() closes the image)
        img = Image.open(BytesIO(content))
        img.format  # Access format to ensure it's readable
    except Exception as e:
        logger.warning(f"Invalid image file: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file"
        )
    
    # Determine file extension from content type
    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp"
    }
    ext = ext_map.get(file.content_type, ".jpg")
    
    # Create entity-specific directory
    uploads_dir = get_uploads_dir()
    entity_dir = uploads_dir / entity_type
    entity_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename: {entity_id}_{short_uuid}{ext}
    short_uuid = generate_short_uuid()
    filename = f"{entity_id}_{short_uuid}{ext}"
    filepath = entity_dir / filename
    
    # Save file
    with open(filepath, "wb") as f:
        f.write(content)
    
    # Set permissions so warehouse-server (nginx user) can read the file
    # Files are in a shared Docker volume, so we need to ensure they're readable
    try:
        import stat
        # Make file readable by all (644 = rw-r--r--)
        filepath.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        # Also ensure parent directories are accessible (755 = rwxr-xr-x)
        # This ensures nginx can traverse the directory tree
        if entity_dir.exists():
            entity_dir.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        if uploads_dir.exists():
            uploads_dir.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        logger.debug(f"Saved file with permissions: {filepath}")
    except Exception as e:
        logger.warning(f"Could not set file permissions for {filepath}: {e}")
        # Continue anyway - permissions might still work if default umask allows it
    
    # Return URL path (relative to API base)
    return f"/uploads/{entity_type}/{filename}"


def delete_profile_picture(avatar_url: Optional[str]) -> None:
    """
    Delete a profile picture file if it exists.
    
    Args:
        avatar_url: The URL path to the file (e.g., "/uploads/bots/123_abc123.jpg")
    """
    if not avatar_url:
        return
    
    try:
        # Remove leading slash and construct full path
        if avatar_url.startswith("/"):
            avatar_url = avatar_url[1:]
        
        filepath = Path("/app/warehouse") / avatar_url
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted profile picture: {filepath}")
    except Exception as e:
        logger.warning(f"Failed to delete profile picture {avatar_url}: {e}")

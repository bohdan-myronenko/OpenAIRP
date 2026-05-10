# ./services/worker/app/main.py

from __future__ import annotations

import os
import logging
import json
from typing import List, Optional, Dict, Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Open Roleplay Worker",
    version="0.1.0",
    description="Worker service for LLM generation requests.",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str


class GenerationSettings(BaseModel):
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = None
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    stop: Optional[List[str]] = None


class ModelConfig(BaseModel):
    api_url: str
    api_key: str
    model_name: str
    custom_prompt: Optional[str] = None


class LLMGenerationRequest(BaseModel):
    chat_history: List[ChatMessage]
    bot_persona: str
    user_persona: Optional[str] = None
    system_prompt: str
    scenario: Optional[str] = None  # Only sent on first message
    example_dialog: Optional[str] = None  # Always sent
    api_config: ModelConfig
    generation_settings: Optional[GenerationSettings] = None


class LLMGenerationResponse(BaseModel):
    reply: str
    model_used: str
    tokens_used: Optional[int] = None


def build_messages(
    chat_history: List[ChatMessage],
    bot_persona: str,
    user_persona: Optional[str],
    system_prompt: str,
    custom_prompt: Optional[str] = None,
    scenario: Optional[str] = None,
    example_dialog: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Build the messages array for OpenAI-compatible API.
    Format: system prompt + scenario (if first message) + persona info + example dialog + chat history
    Uses custom_prompt if provided, otherwise uses system_prompt.
    """
    messages: List[Dict[str, str]] = []

    # Use custom prompt if provided, otherwise use system prompt
    base_prompt = custom_prompt if custom_prompt else system_prompt

    # Build system message with prompt, scenario (if provided), bot persona, user persona, and example dialog
    system_content_parts = [base_prompt]
    
    # Add scenario only if provided (should only be on first message)
    if scenario:
        system_content_parts.append(f"\n\nScenario:\n{scenario}")
    
    if bot_persona:
        system_content_parts.append(f"\n\nBot Persona:\n{bot_persona}")
    
    if user_persona:
        system_content_parts.append(f"\n\nUser Persona:\n{user_persona}")
    
    # Add example dialog (always sent if provided)
    if example_dialog:
        system_content_parts.append(f"\n\nExample Dialog:\n{example_dialog}")
    
    system_content = "\n".join(system_content_parts)
    messages.append({"role": "system", "content": system_content})

    # Add chat history
    for msg in chat_history:
        messages.append({"role": msg.role, "content": msg.content})

    return messages


@app.get("/")
async def root():
    return {"status": "ok", "service": "worker"}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "worker"}


@app.post("/generate", response_model=LLMGenerationResponse)
async def generate_reply(request: LLMGenerationRequest):
    """
    Generate a bot reply using OpenAI-compatible API.
    
    Takes chat history, bot persona, user persona, system prompt, model configuration,
    and generation settings, formats them according to OpenAI's chat completion API,
    and returns the generated reply.
    """
    try:
        # Build messages array
        messages = build_messages(
            request.chat_history,
            request.bot_persona,
            request.user_persona,
            request.system_prompt,
            request.api_config.custom_prompt,
            request.scenario,
            request.example_dialog,
        )

        # Get generation settings (use defaults if not provided)
        settings = request.generation_settings or GenerationSettings()
        
        # Use model name from api_config, fallback to settings.model
        model_name = request.api_config.model_name or settings.model
        
        # Prepare API parameters (OpenAI-compatible format)
        api_params: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "frequency_penalty": settings.frequency_penalty,
            "presence_penalty": settings.presence_penalty,
        }
        
        if settings.max_tokens:
            api_params["max_tokens"] = settings.max_tokens
        
        if settings.stop:
            api_params["stop"] = settings.stop

        logger.info(f"Calling API at {request.api_config.api_url} with model: {model_name}")
        
        # Make HTTP request to the API endpoint
        async with httpx.AsyncClient(timeout=120.0) as client:
            headers = {
                "Authorization": f"Bearer {request.api_config.api_key}",
                "Content-Type": "application/json",
            }
            
            response = await client.post(
                request.api_config.api_url,
                json=api_params,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()
        
        # Extract reply from response (OpenAI-compatible format)
        if "choices" not in result or len(result["choices"]) == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API returned no choices",
            )
        
        reply = result["choices"][0]["message"]["content"]
        if not reply:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API returned empty reply",
            )

        # Get token usage if available
        tokens_used = None
        if "usage" in result:
            usage = result["usage"]
            tokens_used = usage.get("total_tokens")

        logger.info(f"Generated reply (tokens: {tokens_used})")

        return LLMGenerationResponse(
            reply=reply,
            model_used=model_name,
            tokens_used=tokens_used,
        )

    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"API error: {e.response.status_code} - {e.response.text}",
        )
    except httpx.TimeoutException as e:
        logger.error(f"Timeout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Request timed out: {str(e)}",
        )
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to contact API: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Error generating reply: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate reply: {str(e)}",
        )


async def stream_generate_reply(request: LLMGenerationRequest) -> AsyncGenerator[str, None]:
    """
    Stream a bot reply using OpenAI-compatible API with Server-Sent Events.
    Yields JSON strings in SSE format.
    """
    try:
        # Build messages array
        messages = build_messages(
            request.chat_history,
            request.bot_persona,
            request.user_persona,
            request.system_prompt,
            request.api_config.custom_prompt,
            request.scenario,
            request.example_dialog,
        )

        # Get generation settings (use defaults if not provided)
        settings = request.generation_settings or GenerationSettings()
        
        # Use model name from api_config, fallback to settings.model
        model_name = request.api_config.model_name or settings.model
        
        # Prepare API parameters (OpenAI-compatible format with streaming)
        api_params: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "frequency_penalty": settings.frequency_penalty,
            "presence_penalty": settings.presence_penalty,
            "stream": True,  # Enable streaming
        }
        
        if settings.max_tokens:
            api_params["max_tokens"] = settings.max_tokens
        
        if settings.stop:
            api_params["stop"] = settings.stop

        logger.info(f"Streaming from API at {request.api_config.api_url} with model: {model_name}")
        
        # Make streaming HTTP request to the API endpoint
        async with httpx.AsyncClient(timeout=300.0) as client:  # Longer timeout for streaming
            headers = {
                "Authorization": f"Bearer {request.api_config.api_key}",
                "Content-Type": "application/json",
            }
            
            async with client.stream(
                "POST",
                request.api_config.api_url,
                json=api_params,
                headers=headers,
            ) as response:
                response.raise_for_status()
                
                # Stream the response as SSE
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    
                    # OpenAI streaming format: "data: {...}\n\n"
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str == "[DONE]":
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            break
                        
                        try:
                            data = json.loads(data_str)
                            # Extract delta content from OpenAI format
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse streaming data: {data_str}")
                            continue

    except httpx.HTTPStatusError as e:
        error_msg = f"API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
    except httpx.TimeoutException as e:
        error_msg = f"Request timed out: {str(e)}"
        logger.error(error_msg)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
    except httpx.RequestError as e:
        error_msg = f"Failed to contact API: {str(e)}"
        logger.error(error_msg)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"
    except Exception as e:
        error_msg = f"Failed to generate reply: {str(e)}"
        logger.error(error_msg, exc_info=True)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"


@app.post("/generate/stream")
async def generate_reply_stream(request: LLMGenerationRequest):
    """
    Stream a bot reply using OpenAI-compatible API.
    Returns Server-Sent Events (SSE) stream.
    """
    return StreamingResponse(
        stream_generate_reply(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable buffering for nginx
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)

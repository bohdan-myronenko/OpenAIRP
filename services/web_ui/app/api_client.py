import json
import logging
import os
from typing import Optional

import requests
import streamlit as st

logger = logging.getLogger(__name__)

# Default for local dev; inside Docker you set API_URL=http://api:8080
API_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")

# Public API URL for browser-accessible resources (images, etc.)
# This should be the external URL that browsers can access
# If not set, we'll try to construct it from the request context
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").rstrip("/")


def api_request(method: str, path: str, **kwargs) -> Optional[requests.Response]:
    """Helper to call the API. Uses HTTP Basic Auth with username from Streamlit-Authenticator if available."""
    if not st.session_state.is_authenticated:
        return None

    url = f"{API_URL}{path}"
    # Extract timeout from kwargs if present, otherwise use default (longer for reroll)
    is_reroll = "/reroll" in path
    request_timeout = kwargs.pop('timeout', 120 if is_reroll else 30)
    try:
        username = st.session_state.get('username')
        if username and 'auth' not in kwargs:
            pass

        if 'cookies' not in kwargs:
            kwargs['cookies'] = {}
        access_token = st.session_state.get('access_token')
        session_token = st.session_state.get('session_token')
        if access_token:
            kwargs['cookies']['access_token'] = access_token
        if session_token:
            kwargs['cookies']['session_token'] = session_token

        response = st.session_state.api_session.request(method, url, timeout=request_timeout, **kwargs)
    except requests.exceptions.RequestException as exc:
        st.error(f"Error contacting API at {url}: {exc}")
        return None

    if response.status_code == 401:
        st.warning("API authentication failed. Some features may not work.")
        return None

    if response.status_code == 204:
        return response

    if not response.ok:
        try:
            payload = response.json()
            detail = payload.get("detail") or payload
        except Exception:
            detail = response.text
        st.error(f"API error {response.status_code} {response.reason}: {detail}")
        return None

    return response


def stream_message(chat_id: str, payload: dict, chat_container) -> tuple[bool, Optional[str], bool]:
    """
    Stream a message and display tokens as they arrive in the chat container.
    Returns (success, error_message, cancelled).
    """
    url = f"{API_URL}/chats/{chat_id}/messages/stream"
    st.session_state.is_streaming = True
    cancelled = False

    try:
        if not st.session_state.is_authenticated:
            return False, "Authentication required", False

        cookies = {}
        if st.session_state.get('access_token'):
            cookies['access_token'] = st.session_state.access_token
        if st.session_state.get('session_token'):
            cookies['session_token'] = st.session_state.session_token

        response = st.session_state.api_session.post(url, json=payload, stream=True, timeout=300, cookies=cookies)

        if response.status_code == 401:
            return False, "API authentication failed", False

        if response.status_code != 200:
            st.session_state.is_streaming = False
            try:
                error_detail = response.json().get("detail", response.text)
            except Exception:
                error_detail = response.text
            return False, f"API error {response.status_code}: {error_detail}", False

        with chat_container:
            message_placeholder = st.empty()
            accumulated_content = ""

            for line in response.iter_lines():
                if not line:
                    continue

                line_str = line.decode('utf-8')
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    try:
                        data = json.loads(data_str)

                        if "error" in data:
                            st.session_state.is_streaming = False
                            return False, data["error"], False

                        if "cancelled" in data:
                            cancelled = True
                            st.session_state.is_streaming = False
                            return False, "Stream cancelled", True

                        if "done" in data:
                            break

                        if "content" in data:
                            if st.session_state.cancel_stream:
                                cancelled = True
                                break

                            accumulated_content += data["content"]
                            bot_avatar = None
                            if chat_id in st.session_state.chat_metadata:
                                bot_avatar_url = st.session_state.chat_metadata[chat_id].get('bot_avatar_url')
                                if bot_avatar_url:
                                    bot_avatar = bot_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{bot_avatar_url}"
                            with message_placeholder.chat_message("assistant", avatar=bot_avatar):
                                st.write(accumulated_content)
                    except json.JSONDecodeError:
                        continue

                if cancelled:
                    st.session_state.is_streaming = False
                    return False, "Stream cancelled", True

        st.session_state.is_streaming = False
        return True, None, False

    except requests.exceptions.Timeout:
        st.session_state.is_streaming = False
        return False, "Request timed out. The model may be taking too long to respond.", False
    except requests.exceptions.RequestException as exc:
        st.session_state.is_streaming = False
        return False, f"Error contacting API: {exc}", False

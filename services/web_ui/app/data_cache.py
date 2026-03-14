import streamlit as st

from api_client import api_request


def load_bots():
    """Load and cache bots list."""
    if "bots_cache" not in st.session_state:
        response = api_request("GET", "/bots")
        if response:
            st.session_state.bots_cache = response.json()
        else:
            st.session_state.bots_cache = []
    return st.session_state.bots_cache


def load_chats():
    """Load and cache chats list."""
    if "chats_cache" not in st.session_state:
        response = api_request("GET", "/chats")
        if response:
            st.session_state.chats_cache = response.json()
        else:
            st.session_state.chats_cache = []
    return st.session_state.chats_cache


def load_models():
    """Load and cache models list."""
    if "models_cache" not in st.session_state:
        response = api_request("GET", "/models")
        if response:
            st.session_state.models_cache = response.json()
        else:
            st.session_state.models_cache = []
    return st.session_state.models_cache


def load_personas():
    """Load and cache personas list."""
    if "personas_cache" not in st.session_state:
        response = api_request("GET", "/personas")
        if response:
            st.session_state.personas_cache = response.json()
        else:
            st.session_state.personas_cache = []
    return st.session_state.personas_cache


def refresh_bots():
    """Clear bots cache to force reload."""
    if "bots_cache" in st.session_state:
        del st.session_state.bots_cache


def refresh_chats():
    """Clear chats cache to force reload."""
    if "chats_cache" in st.session_state:
        del st.session_state.chats_cache


def refresh_models():
    """Clear models cache to force reload."""
    if "models_cache" in st.session_state:
        del st.session_state.models_cache


def refresh_personas():
    """Clear personas cache to force reload."""
    if "personas_cache" in st.session_state:
        del st.session_state.personas_cache

import requests
import streamlit as st
import extra_streamlit_components as stx


def init_page_config():
    st.set_page_config(
        page_title="ORP",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )


def init_session_state():
    if "current_chat_id" not in st.session_state:
        st.session_state.current_chat_id = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "selected_model_id" not in st.session_state:
        st.session_state.selected_model_id = None
    if "generation_settings" not in st.session_state:
        st.session_state.generation_settings = {
            "temperature": 0.7,
            "max_tokens": None,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
        }
    if "chat_metadata" not in st.session_state:
        st.session_state.chat_metadata = {}
    if "show_settings_modal" not in st.session_state:
        st.session_state.show_settings_modal = False
    if "editing_message_id" not in st.session_state:
        st.session_state.editing_message_id = None
    if "editing_message_content" not in st.session_state:
        st.session_state.editing_message_content = ""
    if "pending_message" not in st.session_state:
        st.session_state.pending_message = None
    if "failed_message" not in st.session_state:
        st.session_state.failed_message = None
    if "failed_message_text" not in st.session_state:
        st.session_state.failed_message_text = None
    if "is_streaming" not in st.session_state:
        st.session_state.is_streaming = False
    if "current_reroll_attempt" not in st.session_state:
        st.session_state.current_reroll_attempt = {}
    if "cancel_stream" not in st.session_state:
        st.session_state.cancel_stream = False
    if "api_session" not in st.session_state:
        st.session_state.api_session = requests.Session()
    if "access_token" not in st.session_state:
        st.session_state.access_token = None
    if "session_token" not in st.session_state:
        st.session_state.session_token = None
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False
    if "cookie_manager" not in st.session_state:
        st.session_state.cookie_manager = stx.CookieManager(key="cookie_manager_main")
    if "current_page" not in st.session_state:
        st.session_state.current_page = None
    if "previous_page" not in st.session_state:
        st.session_state.previous_page = None


def get_cookie_manager():
    return st.session_state.cookie_manager

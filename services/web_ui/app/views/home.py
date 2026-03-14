import streamlit as st

from data_cache import load_bots, load_chats, load_models, load_personas


def show_home():
    """Home page with overview."""
    st.header("Welcome to ORP")
    st.markdown("""
    This is your interactive roleplay platform. Use the sidebar to navigate:
    
    - **Bots**: View and manage your AI bots
    - **Chats**: View your chat history
    - **Chat Interface**: Start chatting with your bots
    - **Models**: Select and configure AI models
    - **Personas**: Manage your user personas
    """)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        bots = load_bots()
        st.metric("Total Bots", len(bots))

    with col2:
        chats = load_chats()
        st.metric("Total Chats", len(chats))

    with col3:
        total_messages = sum(chat.get('message_count', 0) for chat in chats)
        st.metric("Total Messages", total_messages)

    with col4:
        models = load_models()
        st.metric("Total Models", len(models))

    with col5:
        personas = load_personas()
        st.metric("Total Personas", len(personas))

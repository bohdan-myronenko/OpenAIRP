import streamlit as st
from auth import init_authenticator, check_is_admin
from views.bots import show_bots_manager
from views.users import show_users_manager
from views.chat_monitor import show_chat_monitor
from views.models import show_models

st.set_page_config(page_title="Admin Dashboard V2", page_icon="🛡️", layout="wide")

init_authenticator()

st.session_state.authenticator.login(location='main')

authentication_status = st.session_state.get('authentication_status')
username = st.session_state.get('username')
name = st.session_state.get('name')

if authentication_status:
    if not check_is_admin(username):
        st.error("You do not have administrative privileges.")
        st.session_state.authenticator.logout('Logout', 'main')
    else:
        st.sidebar.title(f"Welcome, {name}")
        st.session_state.authenticator.logout('Logout', 'sidebar')

        page = st.sidebar.radio("Navigation", [
            "Bot Management", 
            "User Accounts", 
            "Chat Monitor",
            "Models"])
        
        st.title("Admin Dashboard")
        st.markdown("---")

        if page == "Bot Management":
            show_bots_manager()
        elif page == "User Accounts":
            show_users_manager()
        elif page == "Chat Monitor":
            show_chat_monitor()
        elif page == "Models":
            show_models()

elif authentication_status is False:
    st.error('Username/password is incorrect')
elif authentication_status is None:
    st.warning('Please enter your username and password')

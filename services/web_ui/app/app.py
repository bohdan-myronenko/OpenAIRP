import logging
import os
import bcrypt

import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

from api_client import API_URL
from auth import authenticate_with_backend_api, check_authentication
from state import get_cookie_manager
from views.bots import show_bots
from views.chat_interface import show_chat_interface
from views.chats import show_chats
from views.home import show_home
from views.models import show_models
from views.personas import show_personas

logger = logging.getLogger(__name__)


def main():
    cookie_manager = get_cookie_manager()

    try:
        prev_auth_status = st.session_state.get('authentication_status')
        prev_username = st.session_state.get('username')

        login_result = st.session_state.authenticator.login(location='main')

        if login_result is not None:
            name, authentication_status, username = login_result
        else:
            authentication_status = st.session_state.get('authentication_status')
            username = st.session_state.get('username')
            name = st.session_state.get('name')

        if login_result is None and st.session_state.get('authentication_status') is True:
            authentication_status = True
            username = st.session_state.get('username')
            name = st.session_state.get('name')

        if authentication_status is True:
            st.session_state.name = name
            st.session_state.username = username
            st.session_state.authentication_status = True
            try:
                with open(st.session_state.auth_config_path) as file:
                    updated_config = yaml.load(file, Loader=SafeLoader)
                st.session_state.auth_config = updated_config
            except Exception:
                pass

            user_password = None
            ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
            ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

            if username == ADMIN_USERNAME and ADMIN_PASSWORD:
                user_password = ADMIN_PASSWORD
            else:
                try:
                    user_info = st.session_state.auth_config.get('credentials', {}).get('usernames', {}).get(username, {})
                    user_password = user_info.get('password', '')
                    if user_password and user_password.startswith('$2b$'):
                        user_password = None
                except Exception as e:
                    logger.error(f"Error getting password from config: {e}")
                    user_password = None

            if user_password and not st.session_state.get('access_token'):
                authenticate_with_backend_api(username, user_password)
        elif authentication_status is False:
            st.session_state.authentication_status = False
            st.error("❌ Incorrect username or password. Please try again.")

            try:
                failed_username = None
                if login_result is not None:
                    _, _, failed_username = login_result
                elif username:
                    failed_username = username

                try:
                    with open(st.session_state.auth_config_path) as file:
                        config = yaml.load(file, Loader=SafeLoader)
                    st.session_state.auth_config = config
                except Exception:
                    config = st.session_state.auth_config.copy() if st.session_state.get('auth_config') else {}

                if failed_username:
                    if 'credentials' not in config:
                        config['credentials'] = {}
                    if 'usernames' not in config['credentials']:
                        config['credentials']['usernames'] = {}

                    if failed_username in config['credentials']['usernames']:
                        user_info = config['credentials']['usernames'][failed_username]
                        current_attempts = user_info.get('failed_login_attempts', 0)
                        user_info['failed_login_attempts'] = current_attempts + 1

                    st.session_state.auth_config_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(st.session_state.auth_config_path, 'w') as file:
                        yaml.dump(config, file, default_flow_style=False, allow_unicode=True)

                    st.session_state.auth_config = config
            except Exception as e:
                logger.error(f"Error updating failed_login_attempts: {e}")

            try:
                with open(st.session_state.auth_config_path) as file:
                    updated_config = yaml.load(file, Loader=SafeLoader)
                st.session_state.auth_config = updated_config
            except Exception:
                pass
    except Exception as e:
        st.error(f"Authentication error: {e}")

    check_authentication()

    if "sync_counter" not in st.session_state:
        st.session_state.sync_counter = 0
    st.session_state.sync_counter += 1

    if not st.session_state.is_authenticated:
        st.markdown("---")
        with st.expander("📝 Register New User"):
            with st.form("register_form"):
                reg_username = st.text_input("Username", key="reg_username")
                reg_email = st.text_input("Email", key="reg_email")
                reg_first_name = st.text_input("First Name (optional)", key="reg_first_name")
                reg_last_name = st.text_input("Last Name (optional)", key="reg_last_name")
                reg_password = st.text_input("Password", type="password", key="reg_password")
                reg_confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm_password")
                submit_registration = st.form_submit_button("Register")

                if submit_registration:
                    if not reg_username or not reg_email or not reg_password:
                        st.error("Username, email, and password are required.")
                    elif reg_password != reg_confirm_password:
                        st.error("Passwords do not match.")
                    else:
                        try:
                            create_user_payload = {
                                "username": reg_username,
                                "email": reg_email,
                                "password": reg_password
                            }

                            response = st.session_state.api_session.post(
                                f"{API_URL}/users",
                                json=create_user_payload,
                                timeout=10
                            )

                            if response.status_code == 201:
                                user_data = response.json()
                                password_hash = bcrypt.hashpw(reg_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                                first_name = reg_first_name.strip() if reg_first_name else ''
                                last_name = reg_last_name.strip() if reg_last_name else ''

                                with open(st.session_state.auth_config_path) as file:
                                    config = yaml.load(file, Loader=SafeLoader)

                                if 'credentials' not in config:
                                    config['credentials'] = {}
                                if 'usernames' not in config['credentials']:
                                    config['credentials']['usernames'] = {}

                                config['credentials']['usernames'][reg_username] = {
                                    'email': reg_email,
                                    'failed_login_attempts': 0,
                                    'first_name': first_name,
                                    'last_name': last_name,
                                    'logged_in': False,
                                    'password': password_hash,
                                    'roles': ['user']
                                }

                                st.session_state.auth_config_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(st.session_state.auth_config_path, 'w') as file:
                                    yaml.dump(config, file, default_flow_style=False, allow_unicode=True)

                                st.session_state.auth_config = config
                                st.session_state.authenticator = stauth.Authenticate(
                                    config['credentials'],
                                    config['cookie']['name'],
                                    config['cookie']['key'],
                                    config['cookie']['expiry_days']
                                )

                                logger.info(f"User {reg_username} registered successfully in both backend and config")
                                st.success('User registered successfully! You can now log in.')
                                st.rerun()
                            elif response.status_code == 400:
                                error_detail = response.json().get("detail", "User already exists")
                                st.error(f"Registration failed: {error_detail}")
                            else:
                                st.error(f"Registration failed: {response.status_code} - {response.text}")
                        except Exception as e:
                            logger.error(f"Registration error: {e}", exc_info=True)
                            st.error(f"Registration error: {str(e)}")

        st.stop()

    st.title("🤖 ORP")
    st.markdown("---")

    with st.sidebar:
        st.markdown("---")
        st.subheader("👤 Account")
        if st.session_state.current_user:
            username = st.session_state.get('username', st.session_state.current_user.get('username', 'Unknown'))
            name = st.session_state.get('name', st.session_state.current_user.get('name', ''))
            email = st.session_state.current_user.get('email', 'N/A')

            st.write(f"**Logged in as:** {username}")
            if name:
                st.write(f"**Name:** {name}")
            st.write(f"**Email:** {email}")

            st.session_state.authenticator.logout('Logout', 'sidebar', key='unique_key')

            st.session_state.save_auth_config()
        else:
            st.warning("Not logged in")

    st.sidebar.title("Navigation")

    # Handle navigation to chat interface
    # This must happen BEFORE determining default_index so the radio button uses the correct page
    if st.session_state.get("navigate_to_chat", False) and st.session_state.get("current_chat_id"):
        st.session_state.current_page = "💭 Chat Interface"
        st.session_state.main_navigation_radio = "💭 Chat Interface"
        st.session_state.navigate_to_chat = False

    # Determine default page index
    # If current_page is set, use it; otherwise if current_chat_id exists, default to Chat Interface
    pages = ["🏠 Home", "🤖 Bots", "💬 Chats", "💭 Chat Interface", "⚙️ Models", "👤 Personas"]
    
    # Determine default page index
    # Priority: 1) current_page if set, 2) Chat Interface if current_chat_id exists, 3) Home
    previous_page = st.session_state.get("previous_page")
    
    # Determine the correct page index
    if st.session_state.get("current_page") in pages:
        default_index = pages.index(st.session_state.current_page)
    elif st.session_state.get("current_chat_id") and not st.session_state.get("navigate_to_chat", False):
        # If a chat is active but we're not navigating to chat (e.g., chat action rerun), go to Chat Interface
        default_index = 3  # Chat Interface
        if st.session_state.get("current_page") != "💭 Chat Interface":
            st.session_state.current_page = "💭 Chat Interface"
            # Update radio state if it doesn't match (but only if radio state doesn't exist yet)
            if "main_navigation_radio" not in st.session_state:
                st.session_state.main_navigation_radio = "💭 Chat Interface"
    else:
        default_index = 0  # Home

    # Use a unique key to force radio button to respect the index on reruns
    page = st.sidebar.radio(
        "Choose a page",
        pages,
        index=default_index if default_index < len(pages) else 0,
        key="main_navigation_radio"
    )
    
    # Update current_page and previous_page
    # This allows us to detect if the user manually navigated away
    page_changed = page != st.session_state.get("current_page")
    old_current_page = st.session_state.get("current_page")
    
    if page_changed:
        # User manually navigated - update previous_page to the old page
        st.session_state.previous_page = old_current_page
        st.session_state.current_page = page
    else:
        # Page didn't change, update current_page to match
        st.session_state.current_page = page
        if previous_page is None:
            # First run, set previous_page to current page
            st.session_state.previous_page = page
    
    # Only force navigation to Chat Interface if:
    # 1. We have a current_chat_id
    # 2. We were already on Chat Interface (previous_page was Chat Interface) - meaning a chat action triggered rerun
    # 3. But now we're not on Chat Interface
    # 4. AND the page didn't change (if page_changed is True, user manually navigated, so allow it)
    # 5. AND we're not navigating to chat (navigate_to_chat handles that case)
    # 6. AND current_page is still Chat Interface (meaning we're staying on Chat Interface but radio button is wrong)
    if (st.session_state.get("current_chat_id") and 
        previous_page == "💭 Chat Interface" and 
        page != "💭 Chat Interface" and
        not page_changed and
        not st.session_state.get("navigate_to_chat", False) and
        st.session_state.get("current_page") == "💭 Chat Interface"):
        st.session_state.current_page = "💭 Chat Interface"
        # Can't modify radio state after widget is created, so just rerun and let the index parameter handle it
        st.rerun()

    if page == "🏠 Home":
        show_home()
    elif page == "🤖 Bots":
        show_bots()
    elif page == "💬 Chats":
        show_chats()
    elif page == "💭 Chat Interface":
        show_chat_interface()
    elif page == "⚙️ Models":
        show_models()
    elif page == "👤 Personas":
        show_personas()

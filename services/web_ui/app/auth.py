import logging
import os
import secrets
from pathlib import Path
from typing import Optional

import bcrypt
import requests
import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

logger = logging.getLogger(__name__)


def save_auth_config():
    """Save the authentication config to file."""
    try:
        st.session_state.auth_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(st.session_state.auth_config_path, 'w') as file:
            yaml.dump(st.session_state.auth_config, file, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        logger.error(f"Error saving auth config: {e}")


def init_authenticator():
    if "authenticator" in st.session_state:
        return

    auth_config_path_env = os.getenv("AUTH_CONFIG_PATH")
    if auth_config_path_env:
        config_path = Path(auth_config_path_env)
    else:
        config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        default_config = {
            'cookie': {
                'expiry_days': 30,
                'key': secrets.token_urlsafe(32),
                'name': 'openrp_auth_cookie'
            },
            'credentials': {
                'usernames': {}
            },
            'pre-authorized': {
                'emails': []
            }
        }
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        config = default_config
    else:
        with open(config_path) as file:
            config = yaml.load(file, Loader=SafeLoader)

    cookie_key = config.get('cookie', {}).get('key', '')
    if not cookie_key or cookie_key.strip() == '' or cookie_key.startswith('#'):
        config['cookie']['key'] = secrets.token_urlsafe(32)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as file:
            yaml.dump(config, file, default_flow_style=False, allow_unicode=True)

    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        if 'credentials' not in config:
            config['credentials'] = {'usernames': {}}
        if 'usernames' not in config['credentials']:
            config['credentials']['usernames'] = {}

        admin_user = config['credentials']['usernames'].get(ADMIN_USERNAME)
        password_needs_update = False

        if not admin_user:
            password_needs_update = True
        elif not admin_user.get('password') or not admin_user.get('password', '').startswith('$2b$'):
            password_needs_update = True

        if password_needs_update:
            password_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            config['credentials']['usernames'][ADMIN_USERNAME] = {
                'email': f"{ADMIN_USERNAME}@admin.local",
                'failed_login_attempts': 0,
                'first_name': 'Admin',
                'last_name': 'User',
                'logged_in': False,
                'password': password_hash,
                'roles': ['admin']
            }
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as file:
                yaml.dump(config, file, default_flow_style=False, allow_unicode=True)
            logger.info(f"Added/updated admin user '{ADMIN_USERNAME}' to authentication config")

    st.session_state.authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )
    st.session_state.auth_config = config
    st.session_state.auth_config_path = config_path
    st.session_state.save_auth_config = save_auth_config

    try:
        sync_backend_users_to_config(config, config_path)
        with open(config_path) as file:
            config = yaml.load(file, Loader=SafeLoader)
        st.session_state.auth_config = config
        st.session_state.authenticator = stauth.Authenticate(
            config['credentials'],
            config['cookie']['name'],
            config['cookie']['key'],
            config['cookie']['expiry_days']
        )
    except Exception as e:
        logger.warning(f"Could not sync backend users to config: {e}")


def sync_backend_users_to_config(config: dict, config_path: Path):
    """Sync users from backend database to streamlit-authenticator config."""
    try:
        API_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")
        response = requests.get(f"{API_URL}/users", timeout=5)

        if response.status_code == 200:
            backend_users = response.json()
            if isinstance(backend_users, dict) and 'users' in backend_users:
                backend_users = backend_users['users']
            elif not isinstance(backend_users, list):
                backend_users = []

            if 'credentials' not in config:
                config['credentials'] = {}
            if 'usernames' not in config['credentials']:
                config['credentials']['usernames'] = {}

            ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
            ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

            config_updated = False
            for user in backend_users:
                username = user.get('username')
                email = user.get('email', '')
                is_admin = user.get('is_admin', False)

                if username and username not in config['credentials']['usernames']:
                    if username == ADMIN_USERNAME and ADMIN_PASSWORD:
                        password = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    else:
                        password = ''

                    name_parts = username.split('@')[0] if '@' in username else username
                    first_name = name_parts
                    last_name = ''

                    config['credentials']['usernames'][username] = {
                        'email': email or f"{username}@user.local",
                        'failed_login_attempts': 0,
                        'first_name': first_name,
                        'last_name': last_name,
                        'logged_in': False,
                        'password': password,
                        'roles': ['admin'] if is_admin else ['user']
                    }
                    config_updated = True
                    logger.info(f"Synced user {username} from backend to config")

            if config_updated:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, 'w') as file:
                    yaml.dump(config, file, default_flow_style=False, allow_unicode=True)
                logger.info("Updated config with users from backend database")
    except Exception as e:
        logger.debug(f"Could not sync backend users: {e}")


def authenticate_with_backend_api(username: str, password: str) -> bool:
    """Authenticate with backend API to get JWT tokens after Streamlit-Authenticator login."""
    try:
        API_URL = os.getenv("API_URL", "http://localhost:8080").rstrip("/")
        url = f"{API_URL}/users/login"
        response = st.session_state.api_session.post(
            url,
            json={"username": username, "password": password, "remember_me": True},
            timeout=10
        )
        if response.status_code == 200:
            access_token = None
            if hasattr(st.session_state.api_session, 'cookies'):
                cookie_jar = st.session_state.api_session.cookies
                if 'access_token_readable' in cookie_jar:
                    access_token = cookie_jar.get('access_token_readable')
                elif 'access_token' in cookie_jar:
                    access_token = cookie_jar.get('access_token')

            if not access_token and 'Set-Cookie' in response.headers:
                set_cookie = response.headers.get('Set-Cookie', '')
                if 'access_token_readable=' in set_cookie:
                    start = set_cookie.find('access_token_readable=') + len('access_token_readable=')
                    end = set_cookie.find(';', start)
                    if end == -1:
                        end = len(set_cookie)
                    access_token = set_cookie[start:end].strip()
                elif 'access_token=' in set_cookie:
                    start = set_cookie.find('access_token=') + len('access_token=')
                    end = set_cookie.find(';', start)
                    if end == -1:
                        end = len(set_cookie)
                    access_token = set_cookie[start:end].strip()

            if access_token:
                st.session_state.access_token = access_token
                return True
    except Exception as e:
        logger.error(f"Error authenticating with backend API: {e}")
    return False


def check_authentication():
    """Check if user is authenticated using Streamlit-Authenticator session state."""
    auth_status = st.session_state.get('authentication_status')

    if auth_status:
        username = st.session_state.get('username')
        name = st.session_state.get('name')

        if username:
            try:
                with open(st.session_state.auth_config_path) as file:
                    current_config = yaml.load(file, Loader=SafeLoader)
                st.session_state.auth_config = current_config
            except Exception:
                pass

            email = ''
            first_name = ''
            last_name = ''
            try:
                user_info = st.session_state.auth_config.get('credentials', {}).get('usernames', {}).get(username, {})
                email = user_info.get('email', '')
                first_name = user_info.get('first_name', '')
                last_name = user_info.get('last_name', '')
                if not name and (first_name or last_name):
                    name = f"{first_name} {last_name}".strip()

                if not email and user_info:
                    email = user_info.get('email', '') or ''
            except Exception:
                pass

            st.session_state.current_user = {
                'username': username,
                'name': name,
                'email': email,
                'first_name': first_name,
                'last_name': last_name
            }
            st.session_state.is_authenticated = True
            logger.info(f"User authenticated: {username}")
            return True

    st.session_state.is_authenticated = False
    st.session_state.current_user = None
    return False

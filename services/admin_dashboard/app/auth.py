import os
import secrets
import bcrypt
import yaml
from pathlib import Path
from yaml.loader import SafeLoader
import streamlit as st
import streamlit_authenticator as stauth

def init_authenticator():
    if "authenticator" in st.session_state:
        return

    auth_config_path_env = os.getenv("AUTH_CONFIG_PATH", "/app/auth/config.yaml")
    config_path = Path(auth_config_path_env)
    
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        default_config = {
            'cookie': {
                'expiry_days': 30,
                'key': secrets.token_urlsafe(32),
                'name': 'openrp_admin_auth_cookie'
            },
            'credentials': {'usernames': {}},
            'pre-authorized': {'emails': []}
        }
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        config = default_config
    else:
        with open(config_path) as file:
            config = yaml.load(file, Loader=SafeLoader)

    # Force a different cookie name for the admin dashboard to isolate sessions
    config['cookie']['name'] = 'openrp_admin_auth_cookie'

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
            with open(config_path, 'w') as file:
                yaml.dump(config, file, default_flow_style=False, allow_unicode=True)

    st.session_state.authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )
    st.session_state.auth_config = config
    st.session_state.auth_config_path = config_path

def check_is_admin(username):
    user_info = st.session_state.auth_config.get('credentials', {}).get('usernames', {}).get(username, {})
    roles = user_info.get('roles', [])
    return 'admin' in roles

def save_auth_config():
    try:
        st.session_state.auth_config_path.parent.mkdir(parents=True, exist_ok=True)
        # Restore the web_ui cookie name so we don't accidentally overwrite the main config's cookie name
        # Actually it's better to just leave the original cookie name in the file
        config_to_save = st.session_state.auth_config.copy()
        with open(st.session_state.auth_config_path, 'r') as file:
            orig_config = yaml.load(file, Loader=SafeLoader)
            if orig_config and 'cookie' in orig_config and 'name' in orig_config['cookie']:
                config_to_save['cookie']['name'] = orig_config['cookie']['name']

        with open(st.session_state.auth_config_path, 'w') as file:
            yaml.dump(config_to_save, file, default_flow_style=False, allow_unicode=True)
    except Exception as e:
        st.error(f"Error saving auth config: {e}")

def update_or_delete_user_in_config(username, delete=False, user_data=None):
    if delete:
        if username in st.session_state.auth_config['credentials']['usernames']:
            del st.session_state.auth_config['credentials']['usernames'][username]
    else:
        if username not in st.session_state.auth_config['credentials']['usernames']:
            st.session_state.auth_config['credentials']['usernames'][username] = {}
        if user_data:
            st.session_state.auth_config['credentials']['usernames'][username].update(user_data)
    save_auth_config()

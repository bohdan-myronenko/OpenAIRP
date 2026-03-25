# ./services/admin_dashboard/app/main.py

import os
import json
import secrets
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

import PySimpleGUI as sg
import requests

# Base URL for the API; can be overridden via environment variable
API_URL = os.getenv("API_URL", "http://localhost:8080")

# Default timeout for API requests (in seconds)
DEFAULT_TIMEOUT = 30


# -----------------------------
# Helper functions
# -----------------------------
def _handle_request_errors(func):
    """Decorator to show a popup on any requests-related error."""

    def wrapper(*args, **kwargs):
        try:
            response = func(*args, **kwargs)
            response.raise_for_status()
            # 204 No Content responses have no body, so skip JSON parsing
            if response.status_code == 204:
                return {"status": "success"}
            # Try to parse JSON; if it fails, show a useful error
            try:
                return response.json()
            except json.JSONDecodeError:
                # If response has no content, that's okay
                if not response.content:
                    return {"status": "success"}
                sg.popup_error("API returned invalid JSON.", title="API Error")
                return None
        except requests.exceptions.Timeout:
            sg.popup_error(
                f"Request to API at {API_URL} timed out after {DEFAULT_TIMEOUT} seconds.",
                title="Timeout Error",
            )
            return None
        except requests.exceptions.RequestException as exc:
            sg.popup_error(
                f"Failed to contact API at {API_URL}.\n\nError: {exc}",
                title="Connection Error",
            )
            return None

    return wrapper


@_handle_request_errors
def api_get_bots(auth=None):
    """Get all bots. Auth is optional but recommended."""
    if auth:
        return requests.get(f"{API_URL}/bots", auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.get(f"{API_URL}/bots", timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_create_bot(payload: Dict[str, Any], auth=None):
    """Create a new bot. Auth is optional but recommended."""
    if auth:
        return requests.post(f"{API_URL}/bots", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.post(f"{API_URL}/bots", json=payload, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_update_bot(bot_id: int, payload: Dict[str, Any], auth=None):
    """Update a bot. Auth is optional but recommended."""
    if auth:
        return requests.put(f"{API_URL}/bots/{bot_id}", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.put(f"{API_URL}/bots/{bot_id}", json=payload, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_delete_bot(bot_id: int, auth=None):
    """Delete a bot. Auth is optional but recommended."""
    if auth:
        return requests.delete(f"{API_URL}/bots/{bot_id}", auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.delete(f"{API_URL}/bots/{bot_id}", timeout=DEFAULT_TIMEOUT)


def fetch_bots(auth=None) -> List[Dict[str, Any]]:
    """Return a list of bots or an empty list on error."""
    data = api_get_bots(auth)
    if not data:
        return []
    # Ensure minimal keys are present
    bots: List[Dict[str, Any]] = []
    for b in data:
        bots.append(
            {
                "bot_id": b.get("bot_id"),
                "title": b.get("title", ""),
                "name": b.get("name", ""),
                "description": b.get("description", ""),
                "persona": b.get("persona", ""),
                "scenario": b.get("scenario", ""),
                "greeting": b.get("greeting", ""),
                "example_dialog": b.get("example_dialog", ""),
                "tags": b.get("tags", []),
            }
        )
    return bots


def bot_form_dialog(
    dialog_title: str,
    name: str = "",
    title: str = "",
    description: str = "",
    persona: str = "",
    scenario: str = "",
    greeting: str = "",
    example_dialog: str = "",
    tags: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Open a modal dialog to create or edit a bot."""
    tags_str = ", ".join(tags or [])
    # Use title if provided, otherwise use name
    title_val = title if title else name

    layout = [
        [sg.Text("Title *"), sg.Input(title_val, key="-TITLE-", size=(40, 1))],
        [sg.Text("Name *"), sg.Input(name, key="-NAME-", size=(40, 1))],
        [sg.Text("Description")],
        [sg.Multiline(description, key="-DESC-", size=(50, 3))],
        [sg.Text("Persona")],
        [sg.Multiline(persona, key="-PERSONA-", size=(50, 5), 
                     tooltip="Bot persona/personality description. Use {{char}} for bot name and {{user}} for persona name.")],
        [sg.Text("Scenario (optional - sent only on first message)")],
        [sg.Multiline(scenario, key="-SCENARIO-", size=(50, 3),
                     tooltip="Brief scenario description. Use {{char}} for bot name and {{user}} for persona name. Only sent on first message.")],
        [sg.Text("Initial Message / Greeting (optional)")],
        [sg.Multiline(greeting, key="-GREETING-", size=(50, 3),
                     tooltip="The bot's introductory message. Always added when creating new chat. Use {{char}} for bot name and {{user}} for persona name.")],
        [sg.Text("Example Dialog (optional - always sent to LLM)")],
        [sg.Multiline(example_dialog, key="-EXAMPLE_DIALOG-", size=(50, 6),
                     tooltip="Example lines showing how the character talks. Always sent to LLM. Use {{char}} for bot name and {{user}} for persona name.")],
        [sg.Text("Tags (comma-separated)")],
        [sg.Input(tags_str, key="-TAGS-", size=(50, 1))],
        [sg.Button("Save", bind_return_key=True), sg.Button("Cancel")],
    ]

    window = sg.Window(dialog_title, layout, modal=True, resizable=True)
    result: Optional[Dict[str, Any]] = None

    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Cancel"):
            break
        if event == "Save":
            title_val = values.get("-TITLE-", "").strip()
            name_val = values.get("-NAME-", "").strip()
            if not title_val or not name_val:
                sg.popup_error("Title and Name cannot be empty.", title="Validation Error")
                continue

            desc_val = values.get("-DESC-", "").strip()
            persona_val = values.get("-PERSONA-", "").strip()
            scenario_val = values.get("-SCENARIO-", "").strip()
            greeting_val = values.get("-GREETING-", "").strip()
            example_dialog_val = values.get("-EXAMPLE_DIALOG-", "").strip()
            tags_raw = values.get("-TAGS-", "")
            tags_list = [
                t.strip() for t in tags_raw.split(",") if t.strip()
            ]

            result = {
                "title": title_val,
                "name": name_val,
                "description": desc_val if desc_val else None,
                "persona": persona_val if persona_val else "",
                "scenario": scenario_val if scenario_val else None,
                "greeting": greeting_val if greeting_val else None,
                "example_dialog": example_dialog_val if example_dialog_val else None,
                "tags": tags_list,
            }
            break

    window.close()
    return result


# -----------------------------
# Bot Management window
# -----------------------------
def import_bots_from_jsonl(filepath: str, auth=None) -> Dict[str, Any]:
    """
    Import bots from a JSONL file.
    
    Expected JSONL format per line:
    {"bot_name":"Name","bot_persona":"Persona contents","Scenario":"Scenario contents","example_dialogs":"Example dialogs contents","Intro":"greeting message"}
    
    Returns a dict with 'success_count', 'error_count', and 'errors' list.
    """
    # Helper to safely get and strip string values (handles None/null)
    def safe_strip(value, default=""):
        if value is None:
            return default
        return str(value).strip() or default
    
    success_count = 0
    error_count = 0
    errors: List[str] = []
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    error_count += 1
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
                    continue
                
                bot_name = safe_strip(data.get("bot_name"))
                if not bot_name:
                    error_count += 1
                    errors.append(f"Line {line_num}: Missing 'bot_name' field")
                    continue
                
                payload = {
                    "name": bot_name,
                    "title": bot_name,  # Use bot_name as title as well
                    "persona": safe_strip(data.get("bot_persona"), ""),
                    "scenario": safe_strip(data.get("Scenario")) or None,
                    "example_dialog": safe_strip(data.get("example_dialogs")) or None,
                    "greeting": safe_strip(data.get("Intro")) or None,
                    "description": None,  # Not provided in JSONL format
                    "tags": [],  # Not provided in JSONL format
                }
                
                # Create the bot via API
                result = api_create_bot(payload, auth)
                if result is not None:
                    success_count += 1
                else:
                    error_count += 1
                    errors.append(f"Line {line_num}: API error creating bot '{bot_name}'")
                    
    except FileNotFoundError:
        return {"success_count": 0, "error_count": 1, "errors": [f"File not found: {filepath}"]}
    except Exception as e:
        return {"success_count": success_count, "error_count": error_count + 1, "errors": errors + [f"Unexpected error: {e}"]}
    
    return {"success_count": success_count, "error_count": error_count, "errors": errors}


def bot_management():
    """Manage bots. Requires admin authentication."""
    # Prompt for admin authentication
    auth = None
    auth_layout = [
        [sg.Text("Admin Authentication Required", font=("Arial", 14))],
        [sg.Text("You must be an admin to access bot management.")],
        [sg.Text("Username:"), sg.Input(key="-USERNAME-")],
        [sg.Text("Password:"), sg.Input(key="-PASSWORD-", password_char="*")],
        [sg.Button("Login"), sg.Button("Cancel")],
    ]
    
    auth_window = sg.Window("Admin Login", auth_layout, modal=True)
    event, values = auth_window.read()
    auth_window.close()
    
    if event == "Cancel" or event != "Login":
        return
    
    if not values["-USERNAME-"] or not values["-PASSWORD-"]:
        sg.popup_error("Username and password are required.", title="Error")
        return
    
    auth = (values["-USERNAME-"], values["-PASSWORD-"])
    
    # Verify admin access by checking /users/me endpoint
    try:
        me_response = requests.get(f"{API_URL}/users/me", auth=auth, timeout=DEFAULT_TIMEOUT)
        me_response.raise_for_status()
        current_user = me_response.json()
        is_admin = current_user.get("is_admin", False)
    except Exception:
        is_admin = False
    
    if not is_admin:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    bots = fetch_bots(auth)

    def refresh_table(window, bots_data: List[Dict[str, Any]]):
        table_values = [
            (
                b.get("bot_id"),
                b.get("name", ""),
                b.get("description", ""),
                ", ".join(b.get("tags", [])),
            )
            for b in bots_data
        ]
        window["-BOT-TABLE-"].update(values=table_values)

    layout = [
        [
            sg.Table(
                values=[
                    (
                        b.get("bot_id"),
                        b.get("name", ""),
                        b.get("description", ""),
                        ", ".join(b.get("tags", [])),
                    )
                    for b in bots
                ],
                headings=["ID", "Name", "Description", "Tags"],
                auto_size_columns=True,
                display_row_numbers=False,
                key="-BOT-TABLE-",
                enable_events=True,
                select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                justification="left",
                num_rows=15,
            )
        ],
        [
            sg.Button("Refresh"),
            sg.Button("Create New"),
            sg.Button("Import JSONL"),
            sg.Button("Edit Selected"),
            sg.Button("Delete Selected"),
            sg.Push(),
            sg.Button("Close"),
        ],
    ]

    window = sg.Window("Bot Management", layout, finalize=True)

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Close"):
            break

        if event == "Refresh":
            bots = fetch_bots(auth)
            refresh_table(window, bots)

        elif event == "Create New":
            payload = bot_form_dialog("Create Bot")
            if payload is None:
                continue

            # Ensure title is set (use name if title not provided)
            if "title" not in payload or not payload["title"]:
                payload["title"] = payload.get("name", "")

            created = api_create_bot(payload, auth)
            if created is not None:
                sg.popup("Bot created successfully.", title="Success")
                bots = fetch_bots(auth)
                refresh_table(window, bots)

        elif event == "Import JSONL":
            # Open file browser to select JSONL file
            filepath = sg.popup_get_file(
                "Select JSONL file to import",
                title="Import Bots from JSONL",
                file_types=(("JSONL Files", "*.jsonl"), ("JSON Lines Files", "*.jsonl"), ("All Files", "*.*")),
                no_window=True,
            )
            if not filepath:
                continue
            
            # Confirm import
            confirm = sg.popup_yes_no(
                f"Import bots from:\n{filepath}\n\nThis will create new bots from each line in the JSONL file.\n\nExpected format per line:\n"
                '{"bot_name":"Name","bot_persona":"Persona","Scenario":"Scenario","example_dialogs":"Example dialogs","Intro":"Greeting"}\n\n'
                "Continue?",
                title="Confirm Import",
            )
            if confirm != "Yes":
                continue
            
            # Perform import
            result = import_bots_from_jsonl(filepath, auth)
            
            # Show results
            msg = f"Import completed!\n\nSuccessfully imported: {result['success_count']} bot(s)\nErrors: {result['error_count']}"
            if result['errors']:
                # Show first 10 errors max
                error_details = "\n".join(result['errors'][:10])
                if len(result['errors']) > 10:
                    error_details += f"\n... and {len(result['errors']) - 10} more errors"
                msg += f"\n\nError details:\n{error_details}"
            
            if result['error_count'] > 0:
                sg.popup(msg, title="Import Results")
            else:
                sg.popup(msg, title="Import Successful")
            
            # Refresh the bot list
            bots = fetch_bots(auth)
            refresh_table(window, bots)

        elif event == "Edit Selected":
            selected_rows = values.get("-BOT-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a bot to edit.", title="No Selection")
                continue

            idx = selected_rows[0]
            bot = bots[idx]
            payload = bot_form_dialog(
                "Edit Bot",
                name=bot.get("name", ""),
                title=bot.get("title", bot.get("name", "")),
                description=bot.get("description", ""),
                persona=bot.get("persona", ""),
                scenario=bot.get("scenario", ""),
                greeting=bot.get("greeting", ""),
                example_dialog=bot.get("example_dialog", ""),
                tags=bot.get("tags", []),
            )
            if payload is None:
                continue

            updated = api_update_bot(bot["bot_id"], payload, auth)
            if updated is not None:
                sg.popup("Bot updated successfully.", title="Success")
                bots = fetch_bots(auth)
                refresh_table(window, bots)

        elif event == "Delete Selected":
            selected_rows = values.get("-BOT-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a bot to delete.", title="No Selection")
                continue

            idx = selected_rows[0]
            bot = bots[idx]
            confirm = sg.popup_yes_no(
                f"Are you sure you want to delete bot '{bot.get('name')}' (ID: {bot.get('bot_id')})?",
                title="Confirm Delete",
            )
            if confirm != "Yes":
                continue

            deleted = api_delete_bot(bot["bot_id"], auth)
            if deleted is not None:
                sg.popup("Bot deleted successfully.", title="Success")
                bots = fetch_bots(auth)
                refresh_table(window, bots)

    window.close()


# -----------------------------
# Account Management
# -----------------------------
@_handle_request_errors
def api_get_users(auth):
    """Get all users. Requires admin authentication."""
    return requests.get(f"{API_URL}/users", auth=auth, timeout=DEFAULT_TIMEOUT)


def api_delete_user(user_id: str, username: str, auth):
    """Delete a user account. Requires admin authentication."""
    try:
        # Delete from backend
        response = requests.delete(f"{API_URL}/users/{user_id}", auth=auth, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        
        # After successful deletion, remove from Streamlit config
        if response.status_code in [200, 204] and username:
            remove_user_from_streamlit_config(username)
        
        return response
    except requests.exceptions.Timeout:
        sg.popup_error(
            f"Request to API at {API_URL} timed out after {DEFAULT_TIMEOUT} seconds.",
            title="Timeout Error",
        )
        return None
    except requests.exceptions.RequestException as exc:
        sg.popup_error(
            f"Failed to contact API at {API_URL}.\n\nError: {exc}",
            title="Connection Error",
        )
        return None


def get_streamlit_config_path():
    """Get the path to the Streamlit Authenticator config file."""
    # Check environment variable first (shared volume in Docker)
    web_ui_config_path = os.getenv("WEB_UI_CONFIG_PATH")
    if web_ui_config_path:
        config_path = Path(web_ui_config_path)
        # Ensure parent directory exists (for shared volume)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        return config_path
    
    # Fallback: Try multiple possible paths for local development
    current_file = Path(__file__)
    possible_paths = [
        # Standard structure: services/admin_dashboard/app/main.py -> services/web_ui/config.yaml
        current_file.parent.parent.parent / "web_ui" / "config.yaml",
        # Alternative: from workspace root
        current_file.parent.parent.parent.parent / "services" / "web_ui" / "config.yaml",
        # Relative path from current directory
        Path("services/web_ui/config.yaml"),
    ]
    
    for path in possible_paths:
        if path and path.exists() and path.is_file():
            return path
    
    # If not found, return the first possible path (will be created if needed)
    if possible_paths:
        return possible_paths[0]
    
    return None


def sync_user_to_streamlit_config(username: str, email: str, password_hash: str, is_admin: bool = False, first_name: str = "", last_name: str = ""):
    """Sync a user to the Streamlit Authenticator config file after creation in backend.
    
    Args:
        username: Username
        email: Email address
        password_hash: Password hash from backend (don't re-hash!)
        is_admin: Whether user is admin
        first_name: First name (optional)
        last_name: Last name (optional)
    """
    try:
        config_path = get_streamlit_config_path()
        if not config_path:
            print(f"Error: Could not determine Streamlit config file path")
            return False
        
        print(f"Syncing user {username} to config at: {config_path}")
        
        # Ensure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing config or create default
        if config_path.exists():
            try:
                with open(config_path, 'r') as file:
                    config = yaml.safe_load(file) or {}
            except Exception as e:
                print(f"Warning: Error reading config file, creating new one: {e}")
                config = {}
        else:
            # Create default config structure
            config = {
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
        
        # Ensure credentials structure exists
        if 'credentials' not in config:
            config['credentials'] = {}
        if 'usernames' not in config['credentials']:
            config['credentials']['usernames'] = {}
        
        # Use provided names or derive from username
        if not first_name:
            name_parts = username.split('@')[0] if '@' in username else username
            first_name = name_parts
        if not last_name:
            last_name = ''
        
        # Check if user already exists in config
        if username in config['credentials']['usernames']:
            # User already exists, update with new password hash and info
            existing_user = config['credentials']['usernames'][username]
            # Always update password hash when provided (use hash from backend, don't re-hash!)
            existing_user['password'] = password_hash
            existing_user['email'] = email
            if first_name:
                existing_user['first_name'] = first_name
            if last_name:
                existing_user['last_name'] = last_name
            if is_admin:
                existing_user['roles'] = ['admin']
            elif 'roles' not in existing_user:
                existing_user['roles'] = ['user']
        else:
            # Add new user to config
            config['credentials']['usernames'][username] = {
                'email': email or f"{username}@user.local",
                'failed_login_attempts': 0,
                'first_name': first_name,
                'last_name': last_name,
                'logged_in': False,
                'password': password_hash,  # Use hash from backend (already hashed)
                'roles': ['admin'] if is_admin else ['user']
            }
        
        # Ensure parent directory exists (important for shared volume)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Ensure parent directory exists (important for shared volume)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save updated config
        try:
            with open(config_path, 'w') as file:
                yaml.dump(config, file, default_flow_style=False, allow_unicode=True)
            print(f"Successfully synced user {username} to Streamlit config")
            return True
        except Exception as write_err:
            print(f"Error: Failed to write config file: {write_err}")
            return False
    except Exception as e:
        # Log error but don't fail user creation
        import traceback
        print(f"Error: Failed to sync user to Streamlit config: {e}")
        print(traceback.format_exc())
        return False


def remove_user_from_streamlit_config(username: str):
    """Remove a user from the Streamlit Authenticator config file after deletion from backend."""
    try:
        config_path = get_streamlit_config_path()
        if not config_path:
            print(f"Error: Could not determine Streamlit config file path")
            return False
        
        print(f"Removing user {username} from config at: {config_path}")
        
        if not config_path.exists():
            print(f"Warning: Streamlit config file not found at {config_path} (user may not exist in config)")
            return True  # Not an error if config doesn't exist
        
        # Load existing config
        try:
            with open(config_path, 'r') as file:
                config = yaml.safe_load(file) or {}
        except Exception as e:
            print(f"Error: Failed to read config file: {e}")
            return False
        
        # Ensure credentials structure exists
        if 'credentials' not in config:
            config['credentials'] = {}
        if 'usernames' not in config['credentials']:
            config['credentials']['usernames'] = {}
        
        # Remove user if exists
        if username in config['credentials']['usernames']:
            del config['credentials']['usernames'][username]
            
            # Ensure parent directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save updated config
            try:
                with open(config_path, 'w') as file:
                    yaml.dump(config, file, default_flow_style=False, allow_unicode=True)
                print(f"Successfully removed user {username} from Streamlit config")
                return True
            except Exception as write_err:
                print(f"Error: Failed to write config file: {write_err}")
                return False
        else:
            print(f"User {username} not found in Streamlit config (may have been already removed)")
            return True  # Not an error if user doesn't exist
        
    except Exception as e:
        import traceback
        print(f"Error: Failed to remove user from Streamlit config: {e}")
        print(traceback.format_exc())
        return False


def api_create_user(payload: Dict[str, Any], auth, first_name: str = "", last_name: str = ""):
    """Create a new user account. Auth is optional (public endpoint)."""
    try:
        if auth:
            response = requests.post(f"{API_URL}/users", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)
        else:
            response = requests.post(f"{API_URL}/users", json=payload, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        if response.status_code == 201:
            user_data = response.json()
            # After successful creation in backend, sync to Streamlit config
            # Use the password_hash from backend response (don't re-hash!)
            username = payload.get('username')
            email = payload.get('email')
            password_hash = user_data.get('password_hash') if isinstance(user_data, dict) else None
            is_admin = user_data.get('is_admin', False) if isinstance(user_data, dict) else False
            
            if username and email and password_hash:
                sync_user_to_streamlit_config(username, email, password_hash, is_admin, first_name, last_name)
            
            return user_data
        return None
    except requests.exceptions.Timeout:
        sg.popup_error(
            f"Request to API at {API_URL} timed out after {DEFAULT_TIMEOUT} seconds.",
            title="Timeout Error",
        )
        return None
    except requests.exceptions.RequestException as exc:
        sg.popup_error(
            f"Failed to contact API at {API_URL}.\n\nError: {exc}",
            title="Connection Error",
        )
        return None


def account_management():
    """Manage user accounts. Admin only."""
    # Prompt for admin authentication
    auth = None
    auth_layout = [
        [sg.Text("Admin Authentication Required", font=("Arial", 14))],
        [sg.Text("You must be an admin to access account management.")],
        [sg.Text("Username:"), sg.Input(key="-USERNAME-")],
        [sg.Text("Password:"), sg.Input(key="-PASSWORD-", password_char="*")],
        [sg.Button("Login"), sg.Button("Cancel")],
    ]
    
    auth_window = sg.Window("Admin Login", auth_layout, modal=True)
    event, values = auth_window.read()
    auth_window.close()
    
    if event == "Cancel" or event != "Login":
        return
    
    if not values["-USERNAME-"] or not values["-PASSWORD-"]:
        sg.popup_error("Username and password are required.", title="Error")
        return
    
    auth = (values["-USERNAME-"], values["-PASSWORD-"])
    
    # Verify admin access by trying to fetch users
    users_response = api_get_users(auth)
    if not users_response:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    # Get current user info to check admin status and prevent self-deletion
    try:
        me_response = requests.get(f"{API_URL}/users/me", auth=auth, timeout=DEFAULT_TIMEOUT)
        me_response.raise_for_status()
        current_user = me_response.json()
        current_user_id = current_user.get("user_id")
        is_admin = current_user.get("is_admin", False)
    except Exception:
        current_user_id = None
        is_admin = False
    
    if not is_admin:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    # Fetch users
    users = users_response if isinstance(users_response, list) else users_response.get("users", [])
    
    def format_datetime(dt_str):
        """Format datetime string for display."""
        if not dt_str:
            return ""
        try:
            from datetime import datetime
            if isinstance(dt_str, str):
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            else:
                dt = dt_str
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return str(dt_str)
    
    def refresh_table(window, users_data: List[Dict[str, Any]]):
        table_values = [
            (
                u.get("user_id"),
                u.get("username", ""),
                u.get("email", ""),
                "Admin" if u.get("is_admin", False) else "User",
                format_datetime(u.get("created_at"))
            )
            for u in users_data
        ]
        window["-USER-TABLE-"].update(values=table_values)
    
    layout = [
        [sg.Text("Account Management", font=("Arial", 16))],
        [
            sg.Table(
                values=[
                    (
                        u.get("user_id"),
                        u.get("username", ""),
                        u.get("email", ""),
                        "Admin" if u.get("is_admin", False) else "User",
                        format_datetime(u.get("created_at"))
                    )
                    for u in users
                ],
                headings=["ID", "Username", "Email", "Account Type", "Created At"],
                auto_size_columns=True,
                display_row_numbers=False,
                key="-USER-TABLE-",
                enable_events=True,
                select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                justification="left",
                num_rows=15,
            )
        ],
        [
            sg.Button("Refresh"),
            sg.Button("Create New"),
            sg.Button("Delete Selected"),
            sg.Push(),
            sg.Button("Close"),
        ],
    ]
    
    window = sg.Window("Account Management", layout, finalize=True)
    
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Close"):
            break
        elif event == "Refresh":
            users_response = api_get_users(auth)
            if users_response:
                users = users_response if isinstance(users_response, list) else users_response.get("users", [])
                refresh_table(window, users)
        elif event == "Delete Selected":
            if not values["-USER-TABLE-"]:
                sg.popup("Please select a user to delete.", title="No Selection")
            else:
                selected_index = values["-USER-TABLE-"][0]
                if selected_index < len(users):
                    selected_user = users[selected_index]
                    selected_user_id = selected_user.get("user_id")
                    selected_username = selected_user.get("username", "")
                    
                    # Prevent deleting self
                    if selected_user_id == current_user_id:
                        sg.popup_error("You cannot delete your own account.", title="Error")
                    else:
                        # Confirm deletion
                        confirm = sg.popup_yes_no(
                            f"Are you sure you want to delete user '{selected_username}' (ID: {selected_user_id})?\n\nThis action cannot be undone!",
                            title="Confirm Deletion"
                        )
                        if confirm == "Yes":
                            result = api_delete_user(selected_user_id, selected_username, auth)
                            if result:
                                sg.popup("User deleted successfully!", title="Success")
                                # Refresh the list
                                users_response = api_get_users(auth)
                                if users_response:
                                    users = users_response if isinstance(users_response, list) else users_response.get("users", [])
                                    refresh_table(window, users)
        elif event == "Create New":
            create_layout = [
                [sg.Text("Create New Account", font=("Arial", 14))],
                [sg.Text("Username:"), sg.Input(key="-NEW-USERNAME-")],
                [sg.Text("Email:"), sg.Input(key="-NEW-EMAIL-")],
                [sg.Text("First Name (optional):"), sg.Input(key="-NEW-FIRST-NAME-")],
                [sg.Text("Last Name (optional):"), sg.Input(key="-NEW-LAST-NAME-")],
                [sg.Text("Password:"), sg.Input(key="-NEW-PASSWORD-", password_char="*")],
                [sg.Button("Create"), sg.Button("Cancel")],
            ]
            create_window = sg.Window("Create Account", create_layout, modal=True)
            create_event, create_values = create_window.read()
            create_window.close()
            
            if create_event == "Create":
                if create_values["-NEW-USERNAME-"] and create_values["-NEW-EMAIL-"] and create_values["-NEW-PASSWORD-"]:
                    payload = {
                        "username": create_values["-NEW-USERNAME-"],
                        "email": create_values["-NEW-EMAIL-"],
                        "password": create_values["-NEW-PASSWORD-"],
                    }
                    # Get first and last name (optional)
                    first_name = create_values.get("-NEW-FIRST-NAME-", "").strip()
                    last_name = create_values.get("-NEW-LAST-NAME-", "").strip()
                    
                    # User creation doesn't require auth (public endpoint)
                    result = api_create_user(payload, None, first_name, last_name)
                    if result:
                        sg.popup("Account created successfully!", title="Success")
                        # Refresh the list
                        users_response = api_get_users(auth)
                        if users_response:
                            users = users_response if isinstance(users_response, list) else users_response.get("users", [])
                            refresh_table(window, users)
                else:
                    sg.popup_error("Username, email, and password are required!", title="Error")
    
    window.close()


@_handle_request_errors
def api_get_user_chats(user_id: str, auth):
    """Get all chats for a specific user. Requires admin authentication."""
    return requests.get(f"{API_URL}/chats/admin/user/{user_id}", auth=auth, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_get_chat_detail(chat_id: str, auth):
    """Get chat details. Requires admin authentication."""
    return requests.get(f"{API_URL}/chats/admin/{chat_id}", auth=auth, timeout=DEFAULT_TIMEOUT)


def chat_monitor():
    """Monitor all user chats. Admin only."""
    # Prompt for admin authentication
    auth = None
    auth_layout = [
        [sg.Text("Admin Authentication Required", font=("Arial", 14))],
        [sg.Text("You must be an admin to access chat monitoring.")],
        [sg.Text("Username:"), sg.Input(key="-USERNAME-")],
        [sg.Text("Password:"), sg.Input(key="-PASSWORD-", password_char="*")],
        [sg.Button("Login"), sg.Button("Cancel")],
    ]
    
    auth_window = sg.Window("Admin Login", auth_layout, modal=True)
    event, values = auth_window.read()
    auth_window.close()
    
    if event == "Cancel" or event != "Login":
        return
    
    if not values["-USERNAME-"] or not values["-PASSWORD-"]:
        sg.popup_error("Username and password are required.", title="Error")
        return
    
    auth = (values["-USERNAME-"], values["-PASSWORD-"])
    
    # Verify admin access by trying to fetch users
    users_response = api_get_users(auth)
    if not users_response:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    # Get users list
    users = users_response if isinstance(users_response, list) else users_response.get("users", [])
    
    if not users:
        sg.popup("No users found.", title="Info")
        return
    
    # Main window with user selection
    user_layout = [
        [sg.Text("Chat Monitor - Select User", font=("Arial", 16))],
        [
            sg.Listbox(
                values=[f"{u.get('user_id')}: {u.get('username', '')} ({u.get('email', '')})" for u in users],
                size=(50, 15),
                key="-USER-LIST-",
                enable_events=True,
            )
        ],
        [sg.Button("Select User"), sg.Button("Refresh Users"), sg.Button("Close")],
    ]
    
    user_window = sg.Window("Chat Monitor - Users", user_layout, modal=False)
    
    selected_user_id = None
    selected_username = None
    
    while True:
        event, values = user_window.read()
        if event in (sg.WIN_CLOSED, "Close"):
            break
        elif event == "Refresh Users":
            users_response = api_get_users(auth)
            if users_response:
                users = users_response if isinstance(users_response, list) else users_response.get("users", [])
                user_window["-USER-LIST-"].update(values=[f"{u.get('user_id')}: {u.get('username', '')} ({u.get('email', '')})" for u in users])
        elif event == "Select User" or (event == "-USER-LIST-" and values["-USER-LIST-"]):
            if values["-USER-LIST-"]:
                selected_text = values["-USER-LIST-"][0]
                # Extract user_id from "user_id: username (email)"
                # user_id is now a UUID string
                try:
                    selected_user_id = selected_text.split(":")[0].strip()
                    selected_username = selected_text.split(":")[1].split("(")[0].strip()
                except:
                    sg.popup_error("Invalid user selection.", title="Error")
                    continue
            else:
                sg.popup("Please select a user.", title="No Selection")
                continue
            
            # Fetch chats for selected user
            chats_response = api_get_user_chats(selected_user_id, auth)
            if not chats_response:
                sg.popup(f"No chats found for user '{selected_username}' or error occurred.", title="Info")
                continue
            
            chats = chats_response if isinstance(chats_response, list) else chats_response.get("chats", [])
            
            if not chats:
                sg.popup(f"No chats found for user '{selected_username}'.", title="Info")
                continue
            
            # Show chats window
            chats_layout = [
                [sg.Text(f"Chats for User: {selected_username} (ID: {selected_user_id})", font=("Arial", 14))],
                [
                    sg.Listbox(
                        values=[f"{c.get('chat_id')}: {c.get('title', 'Untitled')} (Bot: {c.get('bot_name', 'Unknown')})" for c in chats],
                        size=(70, 15),
                        key="-CHAT-LIST-",
                        enable_events=True,
                    )
                ],
                [sg.Button("View Chat"), sg.Button("Back to Users"), sg.Button("Close")],
            ]
            
            chats_window = sg.Window("Chat Monitor - Chats", chats_layout, modal=False)
            
            while True:
                chat_event, chat_values = chats_window.read()
                if chat_event in (sg.WIN_CLOSED, "Close"):
                    chats_window.close()
                    break
                elif chat_event == "Back to Users":
                    chats_window.close()
                    break
                elif chat_event == "View Chat" or (chat_event == "-CHAT-LIST-" and chat_values["-CHAT-LIST-"]):
                    if chat_values["-CHAT-LIST-"]:
                        selected_chat_text = chat_values["-CHAT-LIST-"][0]
                        # Extract chat_id from "chat_id: title (Bot: bot_name)"
                        try:
                            selected_chat_id = selected_chat_text.split(":")[0].strip()
                        except:
                            sg.popup_error("Invalid chat selection.", title="Error")
                            continue
                    else:
                        sg.popup("Please select a chat.", title="No Selection")
                        continue
                    
                    # Fetch chat details
                    chat_detail_response = api_get_chat_detail(selected_chat_id, auth)
                    if not chat_detail_response:
                        sg.popup_error("Failed to load chat details.", title="Error")
                        continue
                    
                    chat_detail = chat_detail_response if isinstance(chat_detail_response, dict) else chat_detail_response.get("chat", {})
                    history = chat_detail.get("history", [])
                    
                    # Format chat history for display
                    history_text = f"Chat ID: {selected_chat_id}\n"
                    history_text += f"Title: {chat_detail.get('title', 'Untitled')}\n"
                    history_text += f"Bot: {chat_detail.get('bot_name', 'Unknown')}\n"
                    history_text += f"Persona: {chat_detail.get('persona_name', 'None')}\n"
                    history_text += "\n" + "="*80 + "\n\n"
                    
                    for msg in history:
                        sender = msg.get("sender", "unknown")
                        content = msg.get("content", "")
                        created_at = msg.get("created_at", "")
                        # Format timestamp
                        try:
                            if isinstance(created_at, str):
                                from datetime import datetime
                                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
                            else:
                                timestamp = str(created_at)
                        except:
                            timestamp = str(created_at)
                        
                        history_text += f"[{timestamp}] {sender.upper()}:\n{content}\n\n"
                    
                    # Show chat history window
                    history_layout = [
                        [sg.Text(f"Chat History - {chat_detail.get('title', 'Untitled')}", font=("Arial", 14))],
                        [
                            sg.Multiline(
                                history_text,
                                size=(80, 25),
                                key="-HISTORY-",
                                disabled=True,
                                autoscroll=True,
                            )
                        ],
                        [sg.Button("Close")],
                    ]
                    
                    history_window = sg.Window("Chat History", history_layout, modal=True)
                    history_event, history_values = history_window.read()
                    history_window.close()
    
    user_window.close()


# -----------------------------
# System Prompt Management
# -----------------------------
@_handle_request_errors
def api_get_system_prompts(auth=None):
    return requests.get(f"{API_URL}/system-prompts", auth=auth, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_get_active_system_prompt(auth=None):
    return requests.get(f"{API_URL}/system-prompts/active", auth=auth, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_create_system_prompt(payload: Dict[str, Any], auth=None):
    return requests.post(f"{API_URL}/system-prompts", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_update_system_prompt(prompt_id: int, payload: Dict[str, Any], auth=None):
    return requests.put(f"{API_URL}/system-prompts/{prompt_id}", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_delete_system_prompt(prompt_id: int, auth=None):
    return requests.delete(f"{API_URL}/system-prompts/{prompt_id}", auth=auth, timeout=DEFAULT_TIMEOUT)


def fetch_system_prompts(auth=None) -> List[Dict[str, Any]]:
    """Return a list of system prompts or an empty list on error."""
    data = api_get_system_prompts(auth)
    if not data:
        return []
    return data


def system_prompt_form_dialog(
    dialog_title: str,
    name: str = "",
    content: str = "",
    description: str = "",
    is_active: bool = False,
) -> Optional[Dict[str, Any]]:
    """Open a modal dialog to create or edit a system prompt."""
    layout = [
        [sg.Text("Name"), sg.Input(name, key="-NAME-")],
        [sg.Text("Description")],
        [sg.Multiline(description, key="-DESC-", size=(50, 3))],
        [sg.Text("Content (System Prompt)")],
        [sg.Multiline(content, key="-CONTENT-", size=(50, 10))],
        [sg.Checkbox("Set as Active", default=is_active, key="-ACTIVE-")],
        [sg.Button("Save", bind_return_key=True), sg.Button("Cancel")],
    ]

    window = sg.Window(dialog_title, layout, modal=True)
    result: Optional[Dict[str, Any]] = None

    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Cancel"):
            break
        if event == "Save":
            name_val = values.get("-NAME-", "").strip()
            if not name_val:
                sg.popup_error("Name cannot be empty.", title="Validation Error")
                continue

            content_val = values.get("-CONTENT-", "").strip()
            if not content_val:
                sg.popup_error("Content cannot be empty.", title="Validation Error")
                continue

            result = {
                "name": name_val,
                "content": content_val,
                "description": values.get("-DESC-", "").strip(),
                "is_active": values.get("-ACTIVE-", False),
            }
            break

    window.close()
    return result


def system_prompt_management():
    """Manage system prompts. Admin only."""
    # Prompt for admin authentication
    auth = None
    auth_layout = [
        [sg.Text("Admin Authentication Required", font=("Arial", 14))],
        [sg.Text("You must be an admin to access system prompt management.")],
        [sg.Text("Username:"), sg.Input(key="-USERNAME-")],
        [sg.Text("Password:"), sg.Input(key="-PASSWORD-", password_char="*")],
        [sg.Button("Login"), sg.Button("Cancel")],
    ]
    
    auth_window = sg.Window("Admin Login", auth_layout, modal=True)
    event, values = auth_window.read()
    auth_window.close()
    
    if event == "Cancel" or event != "Login":
        return
    
    if not values["-USERNAME-"] or not values["-PASSWORD-"]:
        sg.popup_error("Username and password are required.", title="Error")
        return
    
    auth = (values["-USERNAME-"], values["-PASSWORD-"])
    
    # Verify admin access by checking /users/me endpoint (same as account_management)
    try:
        me_response = requests.get(f"{API_URL}/users/me", auth=auth, timeout=DEFAULT_TIMEOUT)
        me_response.raise_for_status()
        current_user = me_response.json()
        is_admin = current_user.get("is_admin", False)
    except Exception:
        is_admin = False
    
    if not is_admin:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    # Fetch system prompts
    prompts_response = api_get_system_prompts(auth)
    prompts = prompts_response if isinstance(prompts_response, list) else []

    def refresh_table(window, prompts_data: List[Dict[str, Any]]):
        table_values = [
            (
                p.get("prompt_id"),
                p.get("name", ""),
                "Yes" if p.get("is_active") else "No",
                p.get("description", "")[:50] + "..." if len(p.get("description", "")) > 50 else p.get("description", ""),
            )
            for p in prompts_data
        ]
        window["-PROMPT-TABLE-"].update(values=table_values)

    layout = [
        [
            sg.Table(
                values=[
                    (
                        p.get("prompt_id"),
                        p.get("name", ""),
                        "Yes" if p.get("is_active") else "No",
                        p.get("description", "")[:50] + "..." if len(p.get("description", "")) > 50 else p.get("description", ""),
                    )
                    for p in prompts
                ],
                headings=["ID", "Name", "Active", "Description"],
                auto_size_columns=True,
                display_row_numbers=False,
                key="-PROMPT-TABLE-",
                enable_events=True,
                select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                justification="left",
                num_rows=15,
            )
        ],
        [
            sg.Button("Refresh"),
            sg.Button("Create New"),
            sg.Button("Edit Selected"),
            sg.Button("Delete Selected"),
            sg.Push(),
            sg.Button("Close"),
        ],
    ]

    window = sg.Window("System Prompt Management", layout, finalize=True)

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Close"):
            break

        if event == "Refresh":
            prompts_response = api_get_system_prompts(auth)
            if prompts_response:
                prompts = prompts_response if isinstance(prompts_response, list) else []
                refresh_table(window, prompts)

        elif event == "Create New":
            payload = system_prompt_form_dialog("Create System Prompt")
            if payload is None:
                continue

            created = api_create_system_prompt(payload, auth)
            if created is not None:
                sg.popup("System prompt created successfully.", title="Success")
                prompts_response = api_get_system_prompts(auth)
                if prompts_response:
                    prompts = prompts_response if isinstance(prompts_response, list) else []
                    refresh_table(window, prompts)

        elif event == "Edit Selected":
            selected_rows = values.get("-PROMPT-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a prompt to edit.", title="No Selection")
                continue

            idx = selected_rows[0]
            prompt = prompts[idx]
            payload = system_prompt_form_dialog(
                "Edit System Prompt",
                name=prompt.get("name", ""),
                content=prompt.get("content", ""),
                description=prompt.get("description", ""),
                is_active=prompt.get("is_active", False),
            )
            if payload is None:
                continue

            updated = api_update_system_prompt(prompt["prompt_id"], payload, auth)
            if updated is not None:
                sg.popup("System prompt updated successfully.", title="Success")
                prompts_response = api_get_system_prompts(auth)
                if prompts_response:
                    prompts = prompts_response if isinstance(prompts_response, list) else []
                    refresh_table(window, prompts)

        elif event == "Delete Selected":
            selected_rows = values.get("-PROMPT-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a prompt to delete.", title="No Selection")
                continue

            idx = selected_rows[0]
            prompt = prompts[idx]
            confirm = sg.popup_yes_no(
                f"Are you sure you want to delete prompt '{prompt.get('name')}' (ID: {prompt.get('prompt_id')})?",
                title="Confirm Delete",
            )
            if confirm != "Yes":
                continue

            deleted = api_delete_system_prompt(prompt["prompt_id"], auth)
            if deleted is not None:
                sg.popup("System prompt deleted successfully.", title="Success")
                prompts_response = api_get_system_prompts(auth)
                if prompts_response:
                    prompts = prompts_response if isinstance(prompts_response, list) else []
                    refresh_table(window, prompts)

    window.close()


# -----------------------------
# Model Management
# -----------------------------
@_handle_request_errors
def api_get_models(auth=None):
    if auth:
        return requests.get(f"{API_URL}/models/admin/all", auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.get(f"{API_URL}/models", timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_get_active_model():
    return requests.get(f"{API_URL}/models/active", timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_create_model(payload: Dict[str, Any], auth=None):
    if auth:
        return requests.post(f"{API_URL}/models", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.post(f"{API_URL}/models", json=payload, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_update_model(model_id: int, payload: Dict[str, Any], auth=None):
    if auth:
        return requests.put(f"{API_URL}/models/{model_id}", json=payload, auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.put(f"{API_URL}/models/{model_id}", json=payload, timeout=DEFAULT_TIMEOUT)


@_handle_request_errors
def api_delete_model(model_id: int, auth=None):
    if auth:
        return requests.delete(f"{API_URL}/models/{model_id}", auth=auth, timeout=DEFAULT_TIMEOUT)
    return requests.delete(f"{API_URL}/models/{model_id}", timeout=DEFAULT_TIMEOUT)


def fetch_models(auth=None) -> List[Dict[str, Any]]:
    """Return a list of models or an empty list on error."""
    data = api_get_models(auth)
    if not data:
        return []
    return data


def model_form_dialog(
    dialog_title: str,
    name: str = "",
    api_url: str = "",
    api_key: str = "",
    model_name: str = "",
    custom_prompt: str = "",
    description: str = "",
    is_active: bool = False,
    is_edit: bool = False,
) -> Optional[Dict[str, Any]]:
    """Open a modal dialog to create or edit a model."""
    # When editing, don't show the existing API key - user can leave blank to keep it
    api_key_label = "API Key (leave blank to keep existing)" if is_edit else "API Key (Bearer token - will be sent as 'Authorization: Bearer <key>')"
    api_key_display = "" if is_edit else api_key  # Don't pre-fill when editing
    
    layout = [
        [sg.Text("Name"), sg.Input(name, key="-NAME-")],
        [sg.Text("API URL (base URL, /chat/completions will be appended automatically)")],
        [sg.Text("Examples:", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • OpenAI: https://api.openai.com/v1", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • Chutes: https://llm.chutes.ai/v1", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • Other proxies: https://your-proxy.com/v1", font=("Helvetica", 8), text_color="black")],
        [sg.Input(api_url, key="-API_URL-", size=(50, 1))],
        [sg.Text(api_key_label)],
        [sg.Text("Examples:", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • OpenAI: sk-...", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • Chutes: Your Chutes API token", font=("Helvetica", 8), text_color="black")],
        [sg.Input(api_key_display, key="-API_KEY-", password_char="*", size=(50, 1))],
        [sg.Text("Model Name (as specified by the API provider)")],
        [sg.Text("Examples:", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • OpenAI: gpt-4o-mini, gpt-4, gpt-3.5-turbo", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • Chutes: deepseek-ai/DeepSeek-V3-0324-TEE", font=("Helvetica", 8), text_color="black")],
        [sg.Text("  • Other: Check your provider's documentation", font=("Helvetica", 8), text_color="black")],
        [sg.Input(model_name, key="-MODEL_NAME-", size=(50, 1))],
        [sg.Text("Description")],
        [sg.Multiline(description, key="-DESC-", size=(50, 3))],
        [sg.Text("Custom Prompt (optional - overrides system prompt for this model)")],
        [sg.Multiline(custom_prompt, key="-CUSTOM_PROMPT-", size=(50, 5))],
        [sg.Checkbox("Set as Active", default=is_active, key="-ACTIVE-")],
        [sg.Button("Save", bind_return_key=True), sg.Button("Cancel")],
    ]

    window = sg.Window(dialog_title, layout, modal=True)
    result: Optional[Dict[str, Any]] = None

    while True:
        event, values = window.read()
        if event in (sg.WINDOW_CLOSED, "Cancel"):
            break
        if event == "Save":
            name_val = values.get("-NAME-", "").strip()
            if not name_val:
                sg.popup_error("Name cannot be empty.", title="Validation Error")
                continue

            api_url_val = values.get("-API_URL-", "").strip()
            if not api_url_val:
                sg.popup_error("API URL cannot be empty.", title="Validation Error")
                continue

            api_key_val = values.get("-API_KEY-", "").strip()
            # API key is required for new models, optional for edits (leave blank to keep existing)
            if not api_key_val and not is_edit:
                sg.popup_error("API Key cannot be empty.", title="Validation Error")
                continue

            model_name_val = values.get("-MODEL_NAME-", "").strip()
            if not model_name_val:
                sg.popup_error("Model Name cannot be empty.", title="Validation Error")
                continue

            result = {
                "name": name_val,
                "api_url": api_url_val,
                "api_key": api_key_val,
                "model_name": model_name_val,
                "custom_prompt": values.get("-CUSTOM_PROMPT-", "").strip() or None,
                "description": values.get("-DESC-", "").strip() or None,
                "is_active": values.get("-ACTIVE-", False),
            }
            break

    window.close()
    return result


def model_management():
    """Manage models. Admin only."""
    # Prompt for admin authentication
    auth = None
    auth_layout = [
        [sg.Text("Admin Authentication Required", font=("Arial", 14))],
        [sg.Text("You must be an admin to access model management.")],
        [sg.Text("Username:"), sg.Input(key="-USERNAME-")],
        [sg.Text("Password:"), sg.Input(key="-PASSWORD-", password_char="*")],
        [sg.Button("Login"), sg.Button("Cancel")],
    ]
    
    auth_window = sg.Window("Admin Login", auth_layout, modal=True)
    event, values = auth_window.read()
    auth_window.close()
    
    if event == "Cancel" or event != "Login":
        return
    
    if not values["-USERNAME-"] or not values["-PASSWORD-"]:
        sg.popup_error("Username and password are required.", title="Error")
        return
    
    auth = (values["-USERNAME-"], values["-PASSWORD-"])
    
    # Verify admin access by checking /users/me endpoint
    try:
        me_response = requests.get(f"{API_URL}/users/me", auth=auth, timeout=DEFAULT_TIMEOUT)
        me_response.raise_for_status()
        current_user = me_response.json()
        is_admin = current_user.get("is_admin", False)
    except Exception:
        is_admin = False
    
    if not is_admin:
        sg.popup_error("Access denied. Admin privileges required.", title="Access Denied")
        return
    
    models = fetch_models(auth)

    def _format_description(desc):
        """Format description for display, handling None values."""
        if desc is None:
            return ""
        desc_str = str(desc)
        if len(desc_str) > 40:
            return desc_str[:40] + "..."
        return desc_str

    def refresh_table(window, models_data: List[Dict[str, Any]]):
        table_values = [
            (
                m.get("model_id"),
                m.get("name", ""),
                m.get("model_name", ""),
                "Yes" if m.get("is_active") else "No",
                _format_description(m.get("description")),
            )
            for m in models_data
        ]
        window["-MODEL-TABLE-"].update(values=table_values)

    layout = [
        [
            sg.Table(
                values=[
                    (
                        m.get("model_id"),
                        m.get("name", ""),
                        m.get("model_name", ""),
                        "Yes" if m.get("is_active") else "No",
                        _format_description(m.get("description")),
                    )
                    for m in models
                ],
                headings=["ID", "Name", "Model", "Active", "Description"],
                auto_size_columns=True,
                display_row_numbers=False,
                key="-MODEL-TABLE-",
                enable_events=True,
                select_mode=sg.TABLE_SELECT_MODE_BROWSE,
                justification="left",
                num_rows=15,
            )
        ],
        [
            sg.Button("Refresh"),
            sg.Button("Create New"),
            sg.Button("Edit Selected"),
            sg.Button("Delete Selected"),
            sg.Push(),
            sg.Button("Close"),
        ],
    ]

    window = sg.Window("Model Management", layout, finalize=True)

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Close"):
            break

        if event == "Refresh":
            models = fetch_models(auth)
            refresh_table(window, models)

        elif event == "Create New":
            payload = model_form_dialog("Create Model")
            if payload is None:
                continue

            created = api_create_model(payload, auth)
            if created is not None:
                sg.popup("Model created successfully.", title="Success")
                models = fetch_models(auth)
                refresh_table(window, models)

        elif event == "Edit Selected":
            selected_rows = values.get("-MODEL-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a model to edit.", title="No Selection")
                continue

            idx = selected_rows[0]
            model = models[idx]
            payload = model_form_dialog(
                "Edit Model",
                name=model.get("name", ""),
                api_url=model.get("api_url", ""),
                api_key="",  # Don't pre-fill API key for security
                model_name=model.get("model_name", ""),
                custom_prompt=model.get("custom_prompt", "") or "",
                description=model.get("description", "") or "",
                is_active=model.get("is_active", False),
                is_edit=True,  # Indicate this is an edit operation
            )
            if payload is None:
                continue

            # If API key is empty (user didn't enter new one), don't update it
            if not payload.get("api_key"):
                payload.pop("api_key", None)

            updated = api_update_model(model["model_id"], payload, auth)
            if updated is not None:
                sg.popup("Model updated successfully.", title="Success")
                models = fetch_models(auth)
                refresh_table(window, models)

        elif event == "Delete Selected":
            selected_rows = values.get("-MODEL-TABLE-", [])
            if not selected_rows:
                sg.popup_error("Please select a model to delete.", title="No Selection")
                continue

            idx = selected_rows[0]
            model = models[idx]
            confirm = sg.popup_yes_no(
                f"Are you sure you want to delete model '{model.get('name')}' (ID: {model.get('model_id')})?",
                title="Confirm Delete",
            )
            if confirm != "Yes":
                continue

            deleted = api_delete_model(model["model_id"], auth)
            if deleted is not None:
                sg.popup("Model deleted successfully.", title="Success")
                models = fetch_models(auth)
                refresh_table(window, models)

    window.close()


# -----------------------------
# Main dashboard
# -----------------------------
def main():

    # Check if user is admin (for Accounts access)
    # We'll check this when they try to access Accounts, not here
    layout = [
        [sg.Text("AI Roleplay System Admin", font=("Arial", 20))],
        [
            sg.Button("Bot Management", size=(16, 2)),
            sg.Button("Models", size=(16, 2)),
            sg.Button("System Prompts", size=(16, 2)),
            sg.Button("Accounts", size=(16, 2)),
            sg.Button("Chat Monitor", size=(16, 2)),
        ],
        [sg.Button("Exit")],
    ]

    window = sg.Window("AI Roleplay Dashboard", layout)

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Exit"):
            break
        if event == "Bot Management":
            bot_management()
        elif event == "Models":
            model_management()
        elif event == "System Prompts":
            system_prompt_management()
        elif event == "Accounts":
            account_management()
        elif event == "Chat Monitor":
            chat_monitor()

    window.close()


if __name__ == "__main__":
    main()

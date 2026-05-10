import streamlit as st
from api_client import api_get, api_post, api_delete
from auth import update_or_delete_user_in_config
import bcrypt

def fetch_users():
    try:
        return api_get("/users")
    except Exception as e:
        st.error(f"Error fetching users: {e}")
        return []

def show_users_manager():
    st.header("User Accounts")

    users_data = fetch_users()
    users = users_data.get("users", []) if isinstance(users_data, dict) else users_data

    if users:
        table_data = []
        for u in users:
            table_data.append({
                "User ID": u.get("user_id"),
                "Username": u.get("username"),
                "Email": u.get("email"),
                "Admin Backend": "✅" if u.get("is_admin") else "❌"
            })
        st.dataframe(table_data, use_container_width=True)
    else:
        st.info("No users found.")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Create New User")
        with st.form("create_user", clear_on_submit=True):
            username = st.text_input("Username *")
            email = st.text_input("Email *")
            password = st.text_input("Password *", type="password")
            first_name = st.text_input("First Name")
            last_name = st.text_input("Last Name")
            is_admin = st.checkbox("Grant Admin Dashboard Access?")
            
            submit = st.form_submit_button("Create User")
            if submit:
                if not username or not email or not password:
                    st.error("Username, Email, and Password are required!")
                else:
                    payload = {
                        "username": username,
                        "email": email,
                        "password": password
                    }
                    try:
                        resp = api_post("/users", payload)
                        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        if password_hash:
                            user_config = {
                                'email': email,
                                'failed_login_attempts': 0,
                                'first_name': first_name,
                                'last_name': last_name,
                                'logged_in': False,
                                'password': password_hash,
                                'roles': ['admin'] if is_admin else ['user']
                            }
                            update_or_delete_user_in_config(username, delete=False, user_data=user_config)
                        st.success("User created successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating user: {e}")

    with col2:
        st.subheader("Delete User")
        if users:
            user_options = {f"{u['username']} ({u['email']})": u for u in users}
            selected_user_str = st.selectbox("Select User", options=list(user_options.keys()))
            selected_user = user_options[selected_user_str]

            if st.button("Delete Selected User"):
                if selected_user['username'] == st.session_state.get('username'):
                    st.error("You cannot delete yourself!")
                else:
                    try:
                        api_delete(f"/users/{selected_user['user_id']}")
                        update_or_delete_user_in_config(selected_user['username'], delete=True)
                        st.success("User deleted successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting user: {e}")

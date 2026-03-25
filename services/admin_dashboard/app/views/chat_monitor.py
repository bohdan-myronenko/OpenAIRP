import streamlit as st
from api_client import api_get
from datetime import datetime
from views.users import fetch_users

def fetch_user_chats(user_id: str):
    try:
        return api_get(f"/chats/admin/user/{user_id}")
    except Exception as e:
        st.error(f"Error fetching chats for user ({user_id}): {e}")
        return None

def fetch_chat_detail(chat_id: str):
    try:
        return api_get(f"/chats/admin/{chat_id}")
    except Exception as e:
        st.error(f"Error fetching chat details ({chat_id}): {e}")
        return None

def show_chat_monitor():
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
    
    
    st.header("Chat Monitor")

    if not users:
        st.info("No users found.")
        return

    # User Selection
    user_options = {u.get("user_id"): f"{u.get('user_id')}: {u.get('username', '')} ({u.get('email', '')})" for u in users}
    
    # Adding an empty option at the start
    options = [""] + list(user_options.keys())
    
    selected_user_id = st.selectbox(
        "Select User", 
        options=options, 
        format_func=lambda x: user_options[x] if x else "Select a user..."
    )

    if selected_user_id:
        # Fetch chats for selected user
        chats_data = fetch_user_chats(selected_user_id)
        chats = chats_data if isinstance(chats_data, list) else (chats_data.get("chats", []) if chats_data else [])
        
        if not chats:
            st.info("No chats found for the selected user.")
            return
        
        # Chat Selection
        chat_options = {c.get("chat_id"): f"{c.get('chat_id')}: {c.get('title', 'Untitled')} (Bot: {c.get('bot_name', 'Unknown')})" for c in chats}
        
        chat_options_list = [""] + list(chat_options.keys())
        selected_chat_id = st.selectbox(
            "Select Chat", 
            options=chat_options_list, 
            format_func=lambda x: chat_options[x] if x else "Select a chat..."
        )

        if selected_chat_id:
            # Fetch chat details
            chat_detail_data = fetch_chat_detail(selected_chat_id)
            if not chat_detail_data:
                st.error("Failed to load chat details.")
                return
                
            chat_detail = chat_detail_data if isinstance(chat_detail_data, dict) and "history" in chat_detail_data else chat_detail_data.get("chat", {})
            history = chat_detail.get("history", [])
            
            st.subheader(f"Chat History - {chat_detail.get('title', 'Untitled')}")
            st.write(f"**Chat ID:** {selected_chat_id}")
            st.write(f"**Bot:** {chat_detail.get('bot_name', 'Unknown')}")
            st.write(f"**Persona:** {chat_detail.get('persona_name', 'None')}")
            st.divider()
            
            # Display history
            if not history:
                st.info("No messages in this chat.")
            else:
                for msg in history:
                    sender = msg.get("sender", "unknown")
                    content = msg.get("content", "")
                    created_at = msg.get("created_at", "")
                    
                    try:
                        if isinstance(created_at, str):
                            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            timestamp = str(created_at)
                    except:
                        timestamp = str(created_at)
                        
                    with st.chat_message("user" if sender.lower() == "user" else "assistant"):
                        st.caption(f"{timestamp}")
                        st.write(content)

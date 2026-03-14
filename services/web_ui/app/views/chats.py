import streamlit as st

from api_client import api_request
from data_cache import load_chats, refresh_chats


def show_chats():
    """Chats management page."""
    st.header("💬 Chat Management")

    chats = load_chats()

    if not chats:
        st.info("No chats found. Start a new chat from the Chat Interface page!")
    else:
        st.subheader("Your Chats")

        for chat in chats:
            chat_id = chat.get('chat_id')
            message_count = chat.get('message_count', 0)
            with st.expander(f"💬 {chat.get('title', 'Untitled Chat')} ({message_count} messages)"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**Chat ID:** {chat_id}")
                    st.write(f"**Messages:** {message_count}")
                with col2:
                    st.write(f"**Bot:** {chat.get('bot_name', 'Unknown')}")
                with col3:
                    last_used = chat.get('last_used')
                    if last_used:
                        if isinstance(last_used, str):
                            last_used_str = last_used
                        else:
                            last_used_str = last_used.strftime("%Y-%m-%d %H:%M:%S")
                        st.write(f"**Last Used:** {last_used_str}")
                    else:
                        st.write("**Last Used:** Never")

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button(f"Open Chat", key=f"open_{chat_id}", use_container_width=True):
                        old_chat_id = st.session_state.get("current_chat_id")
                        # Clear chat-related state when switching chats
                        if old_chat_id != chat_id:
                            st.session_state.failed_message = None
                            st.session_state.failed_message_text = None
                            st.session_state.pending_message = None
                            st.session_state.current_reroll_attempt = {}
                        st.session_state.current_chat_id = chat_id
                        st.session_state.navigate_to_chat = True
                        st.rerun()
                with col_btn2:
                    if st.button(f"🗑️ Delete", key=f"delete_{chat.get('chat_id')}", use_container_width=True, type="secondary"):
                        chat_id = chat.get('chat_id')
                        response = api_request("DELETE", f"/chats/{chat_id}")
                        if response or response is None:
                            st.success("Chat deleted successfully!")
                            if st.session_state.current_chat_id == chat_id:
                                st.session_state.current_chat_id = None
                            refresh_chats()
                            st.rerun()
                        else:
                            st.error("Failed to delete chat. Please try again.")

        if st.button("🔄 Refresh Chats List"):
            refresh_chats()
            st.rerun()

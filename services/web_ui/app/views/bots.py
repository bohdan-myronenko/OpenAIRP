from datetime import datetime

import streamlit as st

from api_client import API_URL, PUBLIC_API_URL, api_request
from data_cache import load_bots, load_chats, refresh_bots, refresh_chats


def show_bots():
    """Bots management page."""
    st.header("🤖 Bot Management")

    tab1, tab2 = st.tabs(["📋 List Bots", "➕ Create Bot"])

    with tab1:
        st.subheader("Available Bots")
        bots = load_bots()

        if not bots:
            st.info("No bots found. Create one using the 'Create Bot' tab!")
        else:
            for bot in bots:
                bot_title = bot.get('title', bot.get('name', 'Unnamed'))
                bot_id = bot.get('bot_id')
                with st.expander(f"🤖 {bot_title} (ID: {bot_id})"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        avatar_url = bot.get('avatar_url')
                        if avatar_url:
                            if PUBLIC_API_URL:
                                full_avatar_url = f"{PUBLIC_API_URL}{avatar_url}"
                            else:
                                full_avatar_url = avatar_url
                            try:
                                st.image(full_avatar_url, width=150, caption="Profile Picture")
                            except Exception as e:
                                st.warning(f"Could not load image: {full_avatar_url}")
                                st.caption(f"Error: {str(e)}")
                                if not PUBLIC_API_URL:
                                    st.info("💡 Tip: Set PUBLIC_API_URL environment variable if images don't load. Current value is empty.")
                        else:
                            st.info("No profile picture")

                        st.write(f"**Name:** {bot.get('name', 'N/A')}")
                        st.write(f"**Description:** {bot.get('description', 'No description')}")
                        persona = bot.get('persona')
                        if persona:
                            st.write(f"**Persona:** {persona}")
                        scenario = bot.get('scenario')
                        if scenario:
                            with st.expander("📖 Scenario"):
                                st.write(scenario)
                        greeting = bot.get('greeting')
                        if greeting:
                            with st.expander("👋 Initial Message"):
                                st.write(greeting)
                        example_dialog = bot.get('example_dialog')
                        if example_dialog:
                            with st.expander("💬 Example Dialog"):
                                st.code(example_dialog, language=None)
                        tags = bot.get("tags") or []
                        if tags:
                            st.write(f"**Tags:** {', '.join(tags)}")
                    with col2:
                        st.write(f"**Bot ID:** {bot_id}")

                        st.markdown("---")
                        if st.button("✏️ Edit Bot", key=f"edit_bot_{bot_id}"):
                            st.session_state[f"editing_bot_{bot_id}"] = True
                            st.rerun()

                        st.markdown("---")
                        st.write("**Upload Profile Picture**")
                        uploaded_file = st.file_uploader(
                            "Choose an image",
                            type=['jpg', 'jpeg', 'png', 'gif', 'webp'],
                            key=f"bot_avatar_{bot_id}"
                        )
                        if uploaded_file is not None:
                            if st.button(f"Upload", key=f"upload_bot_{bot_id}"):
                                files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                                url = f"{API_URL}/bots/{bot_id}/avatar"
                                try:
                                    cookies = {}
                                    if st.session_state.access_token:
                                        cookies['access_token'] = st.session_state.access_token
                                    if st.session_state.session_token:
                                        cookies['session_token'] = st.session_state.session_token
                                    response = st.session_state.api_session.post(
                                        url, files=files, cookies=cookies, timeout=30
                                    )
                                    if response.status_code == 200:
                                        st.success("Profile picture uploaded successfully!")
                                        refresh_bots()
                                        st.rerun()
                                    else:
                                        try:
                                            error_detail = response.json().get("detail", response.text)
                                        except Exception:
                                            error_detail = response.text
                                        st.error(f"Upload failed: {error_detail}")
                                except Exception as e:
                                    st.error(f"Error uploading file: {e}")

                    if st.session_state.get(f"editing_bot_{bot_id}", False):
                        st.markdown("---")
                        st.subheader("✏️ Edit Bot")
                        with st.form(f"edit_bot_form_{bot_id}"):
                            edit_title = st.text_input("Bot Title *", value=bot.get('title', ''), key=f"edit_title_{bot_id}")
                            edit_name = st.text_input("Bot Name *", value=bot.get('name', ''), key=f"edit_name_{bot_id}")
                            edit_description = st.text_area("Description", value=bot.get('description', '') or '', key=f"edit_desc_{bot_id}")
                            edit_persona = st.text_area("Persona", value=bot.get('persona', '') or '', key=f"edit_persona_{bot_id}")
                            edit_tags_input = st.text_input("Tags", value=', '.join(bot.get("tags", [])), key=f"edit_tags_{bot_id}")

                            st.markdown("---")
                            st.write("**Advanced Settings**")

                            edit_scenario = st.text_area(
                                "Scenario (optional)",
                                value=bot.get('scenario', '') or '',
                                key=f"edit_scenario_{bot_id}",
                                help="Use {{char}} for bot name and {{user}} for persona name. Only sent on the first message."
                            )

                            edit_greeting = st.text_area(
                                "Initial Message (optional)",
                                value=bot.get('greeting', '') or '',
                                key=f"edit_greeting_{bot_id}",
                                help="Use {{char}} for bot name and {{user}} for persona name. This will be the first message in every new chat."
                            )

                            edit_example_dialog = st.text_area(
                                "Example Dialog (optional)",
                                value=bot.get('example_dialog', '') or '',
                                key=f"edit_example_dialog_{bot_id}",
                                help="Use {{char}} for bot name and {{user}} for persona name. Always sent to LLM to maintain character voice.",
                                height=150
                            )

                            col_submit, col_cancel = st.columns(2)
                            with col_submit:
                                submitted = st.form_submit_button("💾 Save Changes", type="primary")
                            with col_cancel:
                                cancelled = st.form_submit_button("❌ Cancel")

                            if cancelled:
                                st.session_state[f"editing_bot_{bot_id}"] = False
                                st.rerun()

                            if submitted:
                                if not edit_title or not edit_name:
                                    st.error("Bot title and name are required!")
                                else:
                                    edit_tags = [tag.strip() for tag in edit_tags_input.split(",") if tag.strip()] if edit_tags_input else []

                                    payload = {
                                        "title": edit_title,
                                        "name": edit_name,
                                        "description": edit_description if edit_description else None,
                                        "persona": edit_persona if edit_persona else "",
                                        "tags": edit_tags,
                                        "scenario": edit_scenario if edit_scenario else None,
                                        "greeting": edit_greeting if edit_greeting else None,
                                        "example_dialog": edit_example_dialog if edit_example_dialog else None,
                                    }

                                    response = api_request("PUT", f"/bots/{bot_id}", json=payload)
                                    if response:
                                        st.success("Bot updated successfully!")
                                        st.session_state[f"editing_bot_{bot_id}"] = False
                                        refresh_bots()
                                        st.rerun()
                                    else:
                                        st.error("Failed to update bot. Please try again.")

                    st.markdown("---")
                    chats = load_chats()
                    bot_chats = [chat for chat in chats if chat.get('bot_id') == bot_id]
                    bot_chats = sorted(bot_chats, key=lambda x: x.get('last_used') or datetime.min, reverse=True)[:10]

                    if bot_chats:
                        with st.expander(f"💬 Recent Chats ({len(bot_chats)})", expanded=False):
                            for chat in bot_chats:
                                chat_id = chat.get('chat_id')
                                chat_col1, chat_col2, chat_col3, chat_col4 = st.columns([0.8, 4, 1, 0.8])
                                with chat_col1:
                                    persona_avatar_url = chat.get('persona_avatar_url')
                                    if persona_avatar_url:
                                        full_persona_avatar_url = persona_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{persona_avatar_url}"
                                        try:
                                            st.image(full_persona_avatar_url, width=40, use_container_width=False)
                                        except Exception:
                                            pass
                                with chat_col2:
                                    if st.button(
                                        f"**{chat.get('title', 'Untitled Chat')}**",
                                        key=f"open_chat_{chat_id}",
                                        use_container_width=True,
                                        help="Click to open this chat"
                                    ):
                                        st.session_state.current_chat_id = chat_id
                                        st.session_state.navigate_to_chat = True
                                        st.rerun()

                                    last_used = chat.get('last_used')
                                    message_count = chat.get('message_count', 0)
                                    metadata_parts = []
                                    if message_count is not None:
                                        metadata_parts.append(f"{message_count} messages")
                                    if last_used:
                                        if isinstance(last_used, str):
                                            last_used_str = last_used
                                        else:
                                            last_used_str = last_used.strftime("%Y-%m-%d %H:%M")
                                        metadata_parts.append(f"Last: {last_used_str}")
                                    if metadata_parts:
                                        st.caption(" • ".join(metadata_parts))
                                with chat_col3:
                                    st.write("")
                                with chat_col4:
                                    if st.button("🗑️", key=f"delete_chat_{chat_id}", help="Delete chat"):
                                        if api_request("DELETE", f"/chats/{chat_id}"):
                                            st.success("Chat deleted!")
                                            refresh_chats()
                                            refresh_bots()
                                            st.rerun()
                    else:
                        st.caption("No chats yet for this bot.")

            if st.button("🔄 Refresh Bots List"):
                refresh_bots()
                st.rerun()

    with tab2:
        st.subheader("Create New Bot")
        with st.form("create_bot_form"):
            title = st.text_input("Bot Title *", placeholder="Enter bot display title")
            name = st.text_input("Bot Name *", placeholder="Enter bot internal name")
            description = st.text_area("Description", placeholder="Enter bot description (optional)")
            persona = st.text_area("Persona", placeholder="Enter bot persona/personality (optional)")
            tags_input = st.text_input("Tags", placeholder="Comma-separated tags (e.g., fantasy, adventure)")

            st.markdown("---")
            st.write("**Advanced Settings**")

            scenario = st.text_area(
                "Scenario (optional)",
                placeholder="Brief scenario description. Sent to LLM only on the first message for disambiguation.",
                help="Use {{char}} for bot name and {{user}} for persona name. Only sent on the first message."
            )

            greeting = st.text_area(
                "Initial Message (optional)",
                placeholder="The bot's introductory message. Always added when creating a new chat (non-editable, non-deletable).",
                help="Use {{char}} for bot name and {{user}} for persona name. This will be the first message in every new chat."
            )

            example_dialog = st.text_area(
                "Example Dialog (optional)",
                placeholder='Example lines showing how the character talks. Always sent to LLM.\n\nExample:\n{{char}}: "Hey! No fair! Don\'t move! Let {{char}} eat you!"\n*The shark woman says in a whiny voice.*\n"I\'m hungry! I need food! Stop being rude!"',
                help="Use {{char}} for bot name and {{user}} for persona name. Always sent to LLM to maintain character voice.",
                height=150
            )

            st.markdown("---")
            st.write("**Profile Picture (optional)**")
            st.caption("You can upload a profile picture after creating the bot, or upload it now and it will be set after creation.")
            avatar_file = st.file_uploader(
                "Choose an image",
                type=['jpg', 'jpeg', 'png', 'gif', 'webp'],
                key="create_bot_avatar"
            )

            submitted = st.form_submit_button("Create Bot", type="primary")

            if submitted:
                if not title or not name:
                    st.error("Bot title and name are required!")
                else:
                    tags = [tag.strip() for tag in tags_input.split(",") if tag.strip()] if tags_input else []

                    payload = {
                        "title": title,
                        "name": name,
                        "description": description if description else None,
                        "persona": persona if persona else "",
                        "tags": tags,
                        "scenario": scenario if scenario else None,
                        "greeting": greeting if greeting else None,
                        "example_dialog": example_dialog if example_dialog else None,
                    }

                    response = api_request("POST", "/bots", json=payload)
                    if response:
                        bot_data = response.json()
                        bot_id = bot_data.get('bot_id')

                        if avatar_file is not None and bot_id:
                            files = {'file': (avatar_file.name, avatar_file, avatar_file.type)}
                            url = f"{API_URL}/bots/{bot_id}/avatar"
                            try:
                                cookies = {}
                                if st.session_state.access_token:
                                    cookies['access_token'] = st.session_state.access_token
                                if st.session_state.session_token:
                                    cookies['session_token'] = st.session_state.session_token
                                upload_response = st.session_state.api_session.post(
                                    url, files=files, cookies=cookies, timeout=30
                                )
                                if upload_response.status_code == 200:
                                    st.success("Bot created and profile picture uploaded successfully!")
                                else:
                                    st.success("Bot created successfully! (Profile picture upload failed)")
                            except Exception as e:
                                st.success(f"Bot created successfully! (Profile picture upload error: {e})")
                        else:
                            st.success("Bot created successfully!")

                        refresh_bots()
                        st.rerun()

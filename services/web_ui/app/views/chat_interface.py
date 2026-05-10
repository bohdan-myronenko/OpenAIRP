import logging

import streamlit as st

from api_client import PUBLIC_API_URL, api_request, stream_message
from data_cache import load_bots, load_chats, load_models, load_personas, refresh_chats

logger = logging.getLogger(__name__)


def show_chat_interface():
    """Interactive chat interface."""
    with st.sidebar:
        if st.session_state.current_chat_id is None:
            st.subheader("Start New Chat")
            bots = load_bots()

            if not bots:
                st.warning("No bots available. Create a bot first!")
            else:
                bot_options = {f"{bot.get('name')} (ID: {bot.get('bot_id')})": bot.get('bot_id') for bot in bots}
                selected_bot_name = st.selectbox("Select a bot", list(bot_options.keys()))

                personas = load_personas()
                persona_options = {"None": None}
                if personas:
                    persona_options.update({f"{p.get('name')} (ID: {p.get('persona_id')})": p.get('persona_id') for p in personas})

                selected_persona_name = st.selectbox("Select User Persona (optional)", list(persona_options.keys()))
                selected_persona_id = persona_options[selected_persona_name]

                chat_title = st.text_input("Chat Title (optional)", placeholder="Leave empty for default")

                if st.button("Start New Chat", type="primary"):
                    selected_bot_id = bot_options[selected_bot_name]
                    payload = {
                        "bot_id": selected_bot_id,
                        "title": chat_title if chat_title else None,
                        "persona_id": selected_persona_id,
                    }
                    response = api_request("POST", "/chats", json=payload)
                    if response:
                        chat = response.json()
                        st.session_state.current_chat_id = chat['chat_id']
                        st.session_state.navigate_to_chat = True
                        st.success(f"Chat created! Chat ID: {chat['chat_id']}")
                        refresh_chats()
                        st.rerun()

            st.markdown("---")
            st.subheader("Load Existing Chat")
            chats = load_chats()
            if chats:
                chat_options = {f"{chat.get('title')} (ID: {chat.get('chat_id')})": chat.get('chat_id') for chat in chats}
                selected_chat_name = st.selectbox("Select a chat", list(chat_options.keys()), key="load_chat_select")

                if st.button("Load Chat"):
                    st.session_state.current_chat_id = chat_options[selected_chat_name]
                    st.session_state.navigate_to_chat = True
                    refresh_chats()
                    st.rerun()
        else:
            st.subheader("Chat Settings")
            st.info("⚙️ Settings are locked for this chat")

            response = api_request("GET", f"/chats/{st.session_state.current_chat_id}")
            if response:
                current_chat = response.json()
                st.write(f"**Bot:** {current_chat.get('bot_name', 'Unknown')}")
                if current_chat.get('persona_name'):
                    st.write(f"**Persona:** {current_chat.get('persona_name')}")
                else:
                    st.write("**Persona:** None")

            if st.button("🔄 Start New Chat", use_container_width=True):
                st.session_state.current_chat_id = None
                st.session_state._settings_synced_chat_id = None
                st.rerun()

        st.markdown("---")
        st.subheader("⚙️ Current Settings")
        models = load_models()
        model_id_to_show = st.session_state.get('selected_model_id')
        active_model = next((m for m in models if m.get('is_active')), None)
        
        current_model = next((m for m in models if m.get('model_id') == model_id_to_show), None) if model_id_to_show else active_model
        
        if current_model:
            model_symbol = "🛡️" if current_model.get('is_admin_model', False) else "💠"
            st.write(f"**Model:** {model_symbol} {current_model.get('name')}")
            st.write(f"**Temperature:** {st.session_state.generation_settings.get('temperature', 0.7)}")
            st.write(f"**Max Tokens:** {st.session_state.generation_settings.get('max_tokens', 'None')}")
        else:
            st.warning("No active model selected!")

        if st.session_state.current_chat_id is not None:
            if st.button("⚙️ Change Chat Settings", use_container_width=True):
                st.session_state.show_settings_modal = True
                st.rerun()

    if st.session_state.current_chat_id is None:
        st.info("👈 Select a bot from the sidebar to start a new chat, or load an existing chat.")
        st.session_state.failed_message = None
        st.session_state.failed_message_text = None
        st.session_state.pending_message = None
    else:
        current_chat_id = st.session_state.current_chat_id
        response = api_request("GET", f"/chats/{current_chat_id}")
        if not response:
            st.error("Failed to load chat. Please try again.")
            st.session_state.current_chat_id = None
            st.session_state.failed_message = None
            st.session_state.failed_message_text = None
            st.session_state.pending_message = None
        else:
            chat = response.json()

            chat_id = chat['chat_id']
            
            # Always sync settings from DB on every load (including refresh)
            # Only fetch user defaults once per chat load to avoid redundant API calls
            if st.session_state.get("_settings_synced_chat_id") != chat_id:
                me_resp = api_request("GET", "/users/me")
                user_defaults = me_resp.json() if me_resp and me_resp.status_code == 200 else {}
                
                st.session_state.generation_settings = {
                    "temperature": chat.get("temperature") if chat.get("temperature") is not None else user_defaults.get("default_temperature", 0.7),
                    "max_tokens": chat.get("max_tokens") if chat.get("max_tokens") is not None else user_defaults.get("default_max_tokens"),
                    "top_p": chat.get("top_p") if chat.get("top_p") is not None else user_defaults.get("default_top_p", 1.0),
                    "frequency_penalty": chat.get("frequency_penalty") if chat.get("frequency_penalty") is not None else user_defaults.get("default_frequency_penalty", 0.0),
                    "presence_penalty": chat.get("presence_penalty") if chat.get("presence_penalty") is not None else user_defaults.get("default_presence_penalty", 0.0),
                }
                
                if chat.get("model_id"):
                    st.session_state.selected_model_id = chat.get("model_id")
                elif user_defaults.get("default_model_id"):
                    st.session_state.selected_model_id = user_defaults.get("default_model_id")
                else:
                    st.session_state.selected_model_id = None
                    
                st.session_state.chat_is_overriding = chat.get("temperature") is not None
                st.session_state._settings_synced_chat_id = chat_id

            if chat_id not in st.session_state.chat_metadata:
                bot_id = chat.get('bot_id')
                persona_id = chat.get('persona_id')

                bot_avatar_url = None
                persona_avatar_url = None

                if bot_id:
                    bot_response = api_request("GET", f"/bots/{bot_id}")
                    if bot_response:
                        bot_data = bot_response.json()
                        bot_avatar_url = bot_data.get('avatar_url')

                if persona_id:
                    persona_response = api_request("GET", f"/personas/{persona_id}")
                    if persona_response:
                        persona_data = persona_response.json()
                        persona_avatar_url = persona_data.get('avatar_url')

                st.session_state.chat_metadata[chat_id] = {
                    "bot_id": bot_id,
                    "bot_name": chat.get('bot_name'),
                    "bot_avatar_url": bot_avatar_url,
                    "persona_id": persona_id,
                    "persona_name": chat.get('persona_name'),
                    "persona_avatar_url": persona_avatar_url,
                }

            metadata = st.session_state.chat_metadata[chat_id]

            if "lightbox_image" not in st.session_state:
                st.session_state.lightbox_image = None

            if st.session_state.show_settings_modal:
                with st.expander("⚙️ Change Model & Generation Settings", expanded=True):
                    models = load_models()

                    if not models:
                        st.warning("No models configured. Please configure models in the admin dashboard.")
                    else:
                        model_options = {}
                        for m in models:
                            symbol = "🛡️" if m.get('is_admin_model', False) else "💠"
                            display_name = f"{symbol} {m.get('name')} ({m.get('model_name')})"
                            model_options[display_name] = m.get('model_id')
                        active_model = next((m for m in models if m.get('is_active')), None)

                        if active_model:
                            default_idx = list(model_options.values()).index(active_model.get('model_id'))
                        else:
                            default_idx = 0

                        selected_model_name = st.selectbox(
                            "Choose a model",
                            list(model_options.keys()),
                            index=default_idx if default_idx < len(model_options) else 0,
                            key="modal_model_select"
                        )

                        selected_model_id = model_options[selected_model_name]

                        st.subheader("Generation Settings")
                        
                        override_defaults = st.checkbox("Override User Defaults for this Chat", value=st.session_state.get("chat_is_overriding", False), help="If unchecked, this chat will dynamically track your global user defaults.")
                        
                        col1, col2 = st.columns(2)

                        with col1:
                            temperature = st.slider(
                                "Temperature",
                                min_value=0.0,
                                max_value=2.0,
                                value=st.session_state.generation_settings.get("temperature", 0.7),
                                step=0.1,
                                help="Controls randomness. Higher = more creative, Lower = more focused",
                                key="modal_temp",
                                disabled=not override_defaults
                            )

                            max_tokens = st.number_input(
                                "Max Tokens",
                                min_value=1,
                                max_value=4096,
                                value=st.session_state.generation_settings.get("max_tokens") or 500,
                                step=50,
                                help="Maximum tokens to generate (None = no limit)",
                                key="modal_max_tokens",
                                disabled=not override_defaults
                            )

                            top_p = st.slider(
                                "Top P (Nucleus Sampling)",
                                min_value=0.0,
                                max_value=1.0,
                                value=st.session_state.generation_settings.get("top_p", 1.0),
                                step=0.1,
                                help="Controls diversity via nucleus sampling",
                                key="modal_top_p",
                                disabled=not override_defaults
                            )

                        with col2:
                            frequency_penalty = st.slider(
                                "Frequency Penalty",
                                min_value=-2.0,
                                max_value=2.0,
                                value=st.session_state.generation_settings.get("frequency_penalty", 0.0),
                                step=0.1,
                                help="Reduces repetition of frequent tokens",
                                key="modal_freq_penalty",
                                disabled=not override_defaults
                            )

                            presence_penalty = st.slider(
                                "Presence Penalty",
                                min_value=-2.0,
                                max_value=2.0,
                                value=st.session_state.generation_settings.get("presence_penalty", 0.0),
                                step=0.1,
                                help="Encourages talking about new topics",
                                key="modal_pres_penalty",
                                disabled=not override_defaults
                            )

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.button("💾 Save Settings", key="modal_save", type="primary", use_container_width=True):
                                selected_model = next((m for m in models if m.get('model_id') == selected_model_id), None)
                                if selected_model:
                                    # Always set selected_model_id first
                                    st.session_state.selected_model_id = selected_model_id
                                    
                                    # Only try to activate the model if it's not an admin model (users can't update admin models)
                                    is_admin_model = selected_model.get('is_admin_model', False)
                                    if not is_admin_model:
                                        update_response = api_request("PUT", f"/models/{selected_model_id}", json={"is_active": True})
                                        if update_response and update_response.status_code == 200:
                                            pass  # Success, model activated
                                        elif update_response and update_response.status_code == 403:
                                            st.warning("Cannot activate this model (permission denied), but generation settings will still be saved.")
                                    # For admin models, we can't activate them but can still use them
                                else:
                                    # If model not found, still save settings but warn user
                                    st.warning("Model not found, but generation settings will still be saved.")

                                if override_defaults:
                                    st.session_state.generation_settings = {
                                        "temperature": temperature,
                                        "max_tokens": max_tokens if max_tokens > 0 else None,
                                        "top_p": top_p,
                                        "frequency_penalty": frequency_penalty,
                                        "presence_penalty": presence_penalty,
                                    }
                                    update_payload = {
                                        "model_id": selected_model_id,
                                        "temperature": temperature,
                                        "max_tokens": max_tokens if max_tokens > 0 else None,
                                        "top_p": top_p,
                                        "frequency_penalty": frequency_penalty,
                                        "presence_penalty": presence_penalty,
                                    }
                                    st.session_state.chat_is_overriding = True
                                else:
                                    # Use {} so the streaming payload doesn't push explicit Null values that would break resolution
                                    # Wait, we want the UI sliders to keep their current displayed values but gray them out, 
                                    # so we don't erase generation_settings here, we just use the backend payload to reset DB.
                                    update_payload = {
                                        "model_id": None,
                                        "temperature": None,
                                        "max_tokens": None,
                                        "top_p": None,
                                        "frequency_penalty": None,
                                        "presence_penalty": None,
                                    }
                                    st.session_state.chat_is_overriding = False
                                    
                                # Update chat in backend
                                api_request("PUT", f"/chats/{chat_id}", json=update_payload)

                                st.session_state._settings_synced_chat_id = None
                                st.session_state.show_settings_modal = False
                                st.success("Chat settings updated!")
                                st.rerun()

                        with col_cancel:
                            if st.button("❌ Cancel", key="modal_cancel", use_container_width=True):
                                st.session_state.show_settings_modal = False
                                st.rerun()

            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"💬 {chat['title']}")
                st.caption(f"Chatting with: **{metadata['bot_name']}** | Chat ID: {chat['chat_id']}")
            with col2:
                if metadata.get('persona_name'):
                    st.info(f"👤 Persona: **{metadata['persona_name']}**")
                else:
                    st.info("👤 No persona")

            st.markdown("---")

            lightbox_html = """
            <style>
            .lightbox-overlay {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0, 0, 0, 0.9);
                z-index: 9999;
                cursor: pointer;
                align-items: center;
                justify-content: center;
            }
            .lightbox-overlay.active {
                display: flex;
            }
            .lightbox-image {
                max-width: 90%;
                max-height: 90%;
                object-fit: contain;
                border-radius: 8px;
            }
            .lightbox-close {
                position: absolute;
                top: 20px;
                right: 30px;
                color: white;
                font-size: 40px;
                font-weight: bold;
                cursor: pointer;
                z-index: 10000;
            }
            .lightbox-close:hover {
                color: #ccc;
            }
            /* Make chat avatars clickable */
            div[data-testid="stChatMessageAvatar"] img,
            div[data-testid="stChatMessageAvatar"] svg {
                cursor: pointer;
                transition: opacity 0.3s, transform 0.2s;
            }
            div[data-testid="stChatMessageAvatar"] img:hover,
            div[data-testid="stChatMessageAvatar"] svg:hover {
                opacity: 0.8;
                transform: scale(1.1);
            }
            </style>
            <div id="lightbox-overlay" class="lightbox-overlay" onclick="closeLightbox()">
                <span class="lightbox-close" onclick="closeLightbox()">&times;</span>
                <img id="lightbox-image" class="lightbox-image" src="" onclick="event.stopPropagation()">
            </div>
            <script>
            function openLightbox(imageUrl) {
                const overlay = document.getElementById('lightbox-overlay');
                const img = document.getElementById('lightbox-image');
                img.src = imageUrl;
                overlay.classList.add('active');
                document.body.style.overflow = 'hidden';
            }
            function closeLightbox() {
                const overlay = document.getElementById('lightbox-overlay');
                overlay.classList.remove('active');
                document.body.style.overflow = 'auto';
            }
            // Close on Escape key
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    closeLightbox();
                }
            });
            
            // Make avatars clickable
            function makeAvatarsClickable() {
                // Find all chat message avatars - try different selectors
                const avatarContainers = document.querySelectorAll('div[data-testid="stChatMessageAvatar"]');
                avatarContainers.forEach(container => {
                    // Check if already made clickable
                    if (container.hasAttribute('data-clickable')) {
                        return;
                    }
                    
                    // Find img tag inside the container
                    const img = container.querySelector('img');
                    if (img && img.src) {
                        // Only make clickable if it's not an SVG data URL
                        if (!img.src.startsWith('data:image/svg')) {
                            container.setAttribute('data-clickable', 'true');
                            container.style.cursor = 'pointer';
                            container.style.transition = 'opacity 0.3s, transform 0.2s';
                            
                            container.addEventListener('click', function(e) {
                                e.stopPropagation();
                                const imageUrl = img.src;
                                if (imageUrl) {
                                    openLightbox(imageUrl);
                                }
                            });
                            
                            // Add hover effect
                            container.addEventListener('mouseenter', function() {
                                this.style.opacity = '0.8';
                                this.style.transform = 'scale(1.1)';
                            });
                            container.addEventListener('mouseleave', function() {
                                this.style.opacity = '1';
                                this.style.transform = 'scale(1)';
                            });
                        }
                    }
                });
            }
            
            // Run on page load and after Streamlit updates
            makeAvatarsClickable();
            setInterval(makeAvatarsClickable, 500);
            
            // Also use MutationObserver to detect new messages
            const observer = new MutationObserver(function(mutations) {
                makeAvatarsClickable();
            });
            observer.observe(document.body, {
                childList: true,
                subtree: true
            });
            </script>
            """
            st.components.v1.html(lightbox_html, height=0)

            chat_container = st.container()

            history_to_show = chat.get("history", [])

            can_reroll = (len(history_to_show) > 0 and
                         history_to_show[-1].get("sender") == "bot")

            with chat_container:
                for idx, msg in enumerate(history_to_show):
                    sender = msg.get("sender", "user")
                    content = msg.get("content", "")
                    message_id = msg.get("message_id")

                    is_greeting = (idx == 0 and sender == "bot")

                    messages_after = len(history_to_show) - idx - 1
                    can_edit = messages_after <= 3 and not is_greeting

                    is_editing = st.session_state.editing_message_id == message_id

                    if sender == "user":
                        user_avatar = None
                        if metadata.get('persona_avatar_url'):
                            persona_avatar_url = metadata['persona_avatar_url']
                            user_avatar = persona_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{persona_avatar_url}"

                        with st.chat_message("user", avatar=user_avatar):
                            if is_editing:
                                edited_content = st.text_area(
                                    "Edit message",
                                    value=st.session_state.editing_message_content or content,
                                    key=f"edit_text_{message_id}",
                                    height=100
                                )
                                col_commit, col_cancel = st.columns(2)
                                with col_commit:
                                    if st.button("✅ Commit", key=f"commit_{message_id}", type="primary", use_container_width=True):
                                        if edited_content.strip():
                                            response = api_request(
                                                "PUT",
                                                f"/chats/{chat_id}/messages/{message_id}",
                                                json={"content": edited_content.strip()}
                                            )
                                            if response:
                                                st.session_state.editing_message_id = None
                                                st.session_state.editing_message_content = ""
                                                st.rerun()
                                            else:
                                                st.error("Failed to update message")
                                        else:
                                            st.error("Message cannot be empty")
                                with col_cancel:
                                    if st.button("❌ Cancel", key=f"cancel_{message_id}", use_container_width=True):
                                        st.session_state.editing_message_id = None
                                        st.session_state.editing_message_content = ""
                                        st.rerun()
                            else:
                                col_content, col_actions = st.columns([10, 2])
                                with col_content:
                                    st.write(content)
                                    if is_greeting:
                                        st.caption("🔒 Initial greeting (non-editable, non-deletable)")
                                with col_actions:
                                    if can_edit:
                                        if st.button("✏️", key=f"edit_{message_id}", help="Edit message", use_container_width=True):
                                            st.session_state.editing_message_id = message_id
                                            st.session_state.editing_message_content = content
                                            st.rerun()
                                    if not is_greeting:
                                        if st.button("🗑️", key=f"delete_{message_id}", help="Delete message and all subsequent", use_container_width=True):
                                            response = api_request("DELETE", f"/chats/{chat_id}/messages/{message_id}")
                                            if response or response is None:
                                                st.session_state.editing_message_id = None
                                                st.rerun()
                                            else:
                                                st.error("Failed to delete message")
                    else:
                        bot_avatar = None
                        if metadata.get('bot_avatar_url'):
                            bot_avatar_url = metadata['bot_avatar_url']
                            bot_avatar = bot_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{bot_avatar_url}"

                        with st.chat_message("assistant", avatar=bot_avatar):
                            is_last_and_bot = (idx == len(history_to_show) - 1 and can_reroll)

                            if is_editing:
                                edited_content = st.text_area(
                                    "Edit message",
                                    value=st.session_state.editing_message_content or content,
                                    key=f"edit_text_{message_id}",
                                    height=100
                                )
                                col_commit, col_cancel = st.columns(2)
                                with col_commit:
                                    if st.button("✅ Commit", key=f"commit_{message_id}", type="primary", use_container_width=True):
                                        if edited_content.strip():
                                            response = api_request(
                                                "PUT",
                                                f"/chats/{chat_id}/messages/{message_id}",
                                                json={"content": edited_content.strip()}
                                            )
                                            if response:
                                                st.session_state.editing_message_id = None
                                                st.session_state.editing_message_content = ""
                                                st.rerun()
                                            else:
                                                st.error("Failed to update message")
                                        else:
                                            st.error("Message cannot be empty")
                                with col_cancel:
                                    if st.button("❌ Cancel", key=f"cancel_{message_id}", use_container_width=True):
                                        st.session_state.editing_message_id = None
                                        st.session_state.editing_message_content = ""
                                        st.rerun()
                            elif is_last_and_bot:
                                total_attempts = msg.get("total_attempts")
                                attempt_number = msg.get("attempt_number")
                                msg_parent_id = msg.get("parent_message_id")
                                if msg_parent_id is None or msg_parent_id == message_id:
                                    parent_message_id = message_id
                                else:
                                    parent_message_id = msg_parent_id

                                if total_attempts and total_attempts > 1:
                                    current_attempt = (attempt_number if attempt_number is not None else 0) + 1
                                    st.caption(f"Attempt {current_attempt} of {total_attempts}")

                                st.write(content)

                                if total_attempts and total_attempts > 1:
                                    nav_col_left, nav_col_mid, nav_col_right = st.columns([1, 8, 1])
                                    with nav_col_left:
                                        current_attempt = attempt_number if attempt_number is not None else 0
                                        if st.button("◀️", key=f"nav_left_{message_id}", help="Previous attempt", use_container_width=True, disabled=(current_attempt <= 0)):
                                            try:
                                                prev_attempt = current_attempt - 1
                                                nav_response = api_request(
                                                    "POST",
                                                    f"/chats/{chat_id}/messages/{parent_message_id}/select-attempt/{prev_attempt}"
                                                )
                                                if nav_response:
                                                    st.rerun()
                                                else:
                                                    st.error("Failed to navigate to previous attempt")
                                            except Exception as e:
                                                st.error(f"Error navigating: {str(e)}")
                                                logger.error(f"Navigation error: {e}", exc_info=True)
                                    with nav_col_mid:
                                        if st.button("🔁 Reroll", key=f"reroll_{chat_id}_{idx}", help="Reroll this response", use_container_width=True):
                                            with st.spinner("Rerolling..."):
                                                reroll_response = api_request("POST", f"/chats/{chat_id}/reroll")
                                                if reroll_response:
                                                    st.rerun()
                                                else:
                                                    st.error("Failed to reroll message")
                                    with nav_col_right:
                                        max_attempt_num = (total_attempts - 1) if total_attempts else 0
                                        if st.button("▶️", key=f"nav_right_{message_id}", help="Next attempt", use_container_width=True, disabled=(attempt_number is None or attempt_number >= max_attempt_num)):
                                            try:
                                                next_attempt = (attempt_number or 0) + 1
                                                nav_response = api_request(
                                                    "POST",
                                                    f"/chats/{chat_id}/messages/{parent_message_id}/select-attempt/{next_attempt}"
                                                )
                                                if nav_response:
                                                    st.rerun()
                                                else:
                                                    st.error("Failed to navigate to next attempt")
                                            except Exception as e:
                                                st.error(f"Error navigating: {str(e)}")
                                                logger.error(f"Navigation error: {e}", exc_info=True)
                                else:
                                    if st.button("🔁 Reroll", key=f"reroll_{chat_id}_{idx}", help="Reroll this response", use_container_width=True):
                                        with st.spinner("Rerolling..."):
                                            reroll_response = api_request("POST", f"/chats/{chat_id}/reroll")
                                            if reroll_response:
                                                st.rerun()
                                            else:
                                                st.error("Failed to reroll message")
                            else:
                                col_content, col_actions = st.columns([10, 1])
                                with col_content:
                                    st.write(content)
                                    if is_greeting:
                                        st.caption("🔒 Initial greeting (non-editable, non-deletable)")
                                with col_actions:
                                    if can_edit:
                                        if st.button("✏️", key=f"edit_{message_id}", help="Edit message", use_container_width=True):
                                            st.session_state.editing_message_id = message_id
                                            st.session_state.editing_message_content = content
                                            st.rerun()

            if st.session_state.is_streaming:
                col_kill, _ = st.columns([1, 5])
                with col_kill:
                    if st.button("⏹️ Stop Generation", key="kill_switch_main", type="secondary", use_container_width=True):
                        st.session_state.cancel_stream = True
                        api_request("POST", f"/chats/{chat_id}/stream/cancel")
                        st.session_state.is_streaming = False
                        st.rerun()

            if st.session_state.failed_message:
                failed_text = st.session_state.failed_message_text or "your message"
                st.error(f"❌ Failed to send message: \"{failed_text[:50]}{'...' if len(failed_text) > 50 else ''}\"")
                st.info("💡 You can try again or dismiss this error to continue chatting.")
                col_retry, col_dismiss = st.columns([1, 1])
                with col_retry:
                    if st.button("🔄 Try Again", key="retry_failed_message", type="primary", use_container_width=True):
                        user_avatar = None
                        if st.session_state.current_chat_id and st.session_state.current_chat_id in st.session_state.chat_metadata:
                            persona_avatar_url = st.session_state.chat_metadata[st.session_state.current_chat_id].get('persona_avatar_url')
                            if persona_avatar_url:
                                user_avatar = persona_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{persona_avatar_url}"
                        with chat_container:
                            with st.chat_message("user", avatar=user_avatar):
                                st.write(st.session_state.failed_message_text)

                        success, error_msg, was_cancelled = stream_message(
                            st.session_state.current_chat_id,
                            st.session_state.failed_message,
                            chat_container
                        )
                        if success:
                            st.session_state.failed_message = None
                            st.session_state.failed_message_text = None
                            st.session_state.pending_message = None
                            st.rerun()
                        elif was_cancelled:
                            st.rerun()
                        else:
                            if error_msg:
                                st.error(f"Failed again: {error_msg}")
                            else:
                                st.error("Failed again. Please check your connection and try again.")
                with col_dismiss:
                    if st.button("❌ Dismiss", key="dismiss_failed_message", use_container_width=True):
                        st.session_state.failed_message = None
                        st.session_state.failed_message_text = None
                        st.session_state.pending_message = None
                        st.rerun()

            st.markdown("---")
            user_input = st.chat_input("Type your message here...")

            if user_input:
                st.session_state.failed_message = None
                st.session_state.failed_message_text = None

                st.session_state.cancel_stream = False

                payload = {
                    "message": user_input
                }
                
                if st.session_state.get('chat_is_overriding', False):
                    payload["generation_settings"] = {
                        "temperature": st.session_state.generation_settings.get("temperature"),
                        "max_tokens": st.session_state.generation_settings.get("max_tokens"),
                        "top_p": st.session_state.generation_settings.get("top_p"),
                        "frequency_penalty": st.session_state.generation_settings.get("frequency_penalty"),
                        "presence_penalty": st.session_state.generation_settings.get("presence_penalty"),
                    }

                user_avatar = None
                if chat_id in st.session_state.chat_metadata:
                    persona_avatar_url = st.session_state.chat_metadata[chat_id].get('persona_avatar_url')
                    if persona_avatar_url:
                        user_avatar = persona_avatar_url if not PUBLIC_API_URL else f"{PUBLIC_API_URL}{persona_avatar_url}"
                with chat_container:
                    with st.chat_message("user", avatar=user_avatar):
                        st.write(user_input)

                success, error_msg, was_cancelled = stream_message(st.session_state.current_chat_id, payload, chat_container)

                if success:
                    st.session_state.failed_message = None
                    st.session_state.failed_message_text = None
                    st.session_state.pending_message = None
                    st.rerun()
                elif was_cancelled:
                    st.rerun()
                else:
                    st.session_state.failed_message = payload
                    st.session_state.failed_message_text = user_input
                    if error_msg:
                        st.error(f"❌ {error_msg}")
                    st.rerun()

import streamlit as st

from api_client import api_request
from data_cache import load_models, refresh_models


def show_models():
    """Model selection and configuration page."""
    st.header("⚙️ Model Selection & Configuration")

    with st.expander("➕ Create New Model", expanded=False):
        with st.form("create_model_form"):
            col1, col2 = st.columns(2)
            with col1:
                model_name = st.text_input("Model Name *", help="Display name for this model")
                api_url = st.text_input("API URL *", help="Base URL for the API (e.g., https://api.openai.com/v1)")
                model_name_field = st.text_input("Model Identifier *", help="The actual model name (e.g., gpt-4, claude-3-opus)")
            with col2:
                api_key = st.text_input("API Key *", type="password", help="API key for authentication")
                description = st.text_area("Description (optional)", help="Description of this model")
                is_active = st.checkbox("Set as Active", help="Make this model active immediately")

            custom_prompt = st.text_area("Custom Prompt (optional)", help="Optional custom system prompt")

            submit = st.form_submit_button("Create Model", type="primary")

            if submit:
                if not model_name or not api_url or not api_key or not model_name_field:
                    st.error("Please fill in all required fields (marked with *)")
                else:
                    model_data = {
                        "name": model_name,
                        "api_url": api_url,
                        "api_key": api_key,
                        "model_name": model_name_field,
                        "description": description if description else None,
                        "custom_prompt": custom_prompt if custom_prompt else None,
                        "is_active": is_active
                    }

                    response = api_request("POST", "/models", json=model_data)
                    if response and response.status_code == 201:
                        st.success("Model created successfully!")
                        refresh_models()
                        st.rerun()
                    else:
                        error_msg = "Failed to create model"
                        if response:
                            try:
                                error_detail = response.json().get("detail", response.text)
                                error_msg = f"Failed to create model: {error_detail}"
                            except Exception:
                                error_msg = f"Failed to create model: {response.status_code} - {response.text}"
                        st.error(error_msg)

    models = load_models()

    if not models:
        st.warning("No models available. Create a model above or wait for admin to configure models.")
    else:
        st.subheader("Select Active Model")
        model_options = {}
        for m in models:
            symbol = "🛡️" if m.get('is_admin_model', False) else "💠"
            display_name = f"{symbol} {m.get('name')} ({m.get('model_name')})"
            model_options[display_name] = m.get('model_id')

        active_model = next((m for m in models if m.get('is_active')), None)

        # Retrieve user defaults if not in session state
        if "generation_settings" not in st.session_state or not st.session_state.generation_settings:
            st.session_state.generation_settings = {}
            me_resp = api_request("GET", "/users/me")
            if me_resp and me_resp.status_code == 200:
                user_data = me_resp.json()
                st.session_state.generation_settings = {
                    "temperature": user_data.get("default_temperature"),
                    "max_tokens": user_data.get("default_max_tokens"),
                    "top_p": user_data.get("default_top_p"),
                    "frequency_penalty": user_data.get("default_frequency_penalty"),
                    "presence_penalty": user_data.get("default_presence_penalty"),
                }
                # Remove None values so get(..., default) works properly
                st.session_state.generation_settings = {k: v for k, v in st.session_state.generation_settings.items() if v is not None}
                
                if user_data.get("default_model_id"):
                    st.session_state.selected_model_id = user_data.get("default_model_id")
        
        # Determine default model to show in selectbox
        saved_model_id = st.session_state.get("selected_model_id")
        if saved_model_id and saved_model_id in model_options.values():
            default_idx = list(model_options.values()).index(saved_model_id)
        elif active_model:
            default_idx = list(model_options.values()).index(active_model.get('model_id'))
        else:
            default_idx = 0

        selected_model_name = st.selectbox(
            "Choose a model",
            list(model_options.keys()),
            index=default_idx if default_idx < len(model_options) else 0
        )

        selected_model_id = model_options[selected_model_name]
        selected_model = next(m for m in models if m.get('model_id') == selected_model_id)

        with st.expander("📋 Model Details", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                model_symbol = "🛡️" if selected_model.get('is_admin_model', False) else "💠"
                st.write(f"**Type:** {model_symbol} {'Admin Model' if selected_model.get('is_admin_model', False) else 'User Model'}")
                st.write(f"**Name:** {selected_model.get('name')}")
                st.write(f"**Model:** {selected_model.get('model_name')}")
                st.write(f"**API URL:** {selected_model.get('api_url')}")
            with col2:
                st.write(f"**Active:** {'Yes' if selected_model.get('is_active') else 'No'}")
                desc = selected_model.get('description')
                if desc:
                    st.write(f"**Description:** {desc}")

            if not selected_model.get('is_admin_model', False):
                st.markdown("---")
                delete_key = f"delete_model_{selected_model_id}"
                confirm_key = f"confirm_delete_{selected_model_id}"

                if st.session_state.get(confirm_key, False):
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Confirm Delete", type="primary", key=f"confirm_{selected_model_id}"):
                            response = api_request("DELETE", f"/models/{selected_model_id}")
                            if response and response.status_code == 204:
                                st.success("Model deleted successfully!")
                                refresh_models()
                                st.session_state[confirm_key] = False
                                st.rerun()
                            else:
                                error_msg = "Failed to delete model"
                                if response:
                                    try:
                                        error_detail = response.json().get("detail", response.text)
                                        error_msg = f"Failed to delete model: {error_detail}"
                                    except Exception:
                                        error_msg = f"Failed to delete model: {response.status_code} - {response.text}"
                                st.error(error_msg)
                    with col2:
                        if st.button("❌ Cancel", key=f"cancel_{selected_model_id}"):
                            st.session_state[confirm_key] = False
                            st.rerun()
                else:
                    if st.button("🗑️ Delete This Model", type="secondary", key=delete_key):
                        st.session_state[confirm_key] = True
                        st.rerun()

        st.subheader("🎛️ Generation Parameters")
        with st.form("generation_settings_form"):
            col1, col2 = st.columns(2)

            with col1:
                temperature = st.slider(
                    "Temperature",
                    min_value=0.0,
                    max_value=2.0,
                    value=st.session_state.generation_settings.get("temperature", 0.7),
                    step=0.1,
                    help="Controls randomness. Higher = more creative, Lower = more focused"
                )

                max_tokens = st.number_input(
                    "Max Tokens",
                    min_value=1,
                    max_value=4096,
                    value=st.session_state.generation_settings.get("max_tokens") or 500,
                    step=50,
                    help="Maximum tokens to generate (None = no limit)"
                )

                top_p = st.slider(
                    "Top P (Nucleus Sampling)",
                    min_value=0.0,
                    max_value=1.0,
                    value=st.session_state.generation_settings.get("top_p", 1.0),
                    step=0.1,
                    help="Controls diversity via nucleus sampling"
                )

            with col2:
                frequency_penalty = st.slider(
                    "Frequency Penalty",
                    min_value=-2.0,
                    max_value=2.0,
                    value=st.session_state.generation_settings.get("frequency_penalty", 0.0),
                    step=0.1,
                    help="Reduces repetition of frequent tokens"
                )

                presence_penalty = st.slider(
                    "Presence Penalty",
                    min_value=-2.0,
                    max_value=2.0,
                    value=st.session_state.generation_settings.get("presence_penalty", 0.0),
                    step=0.1,
                    help="Encourages talking about new topics"
                )

            submitted = st.form_submit_button("💾 Save Settings", type="primary")

            if submitted:
                st.session_state.generation_settings = {
                    "temperature": temperature,
                    "max_tokens": max_tokens if max_tokens > 0 else None,
                    "top_p": top_p,
                    "frequency_penalty": frequency_penalty,
                    "presence_penalty": presence_penalty,
                }
                st.session_state.selected_model_id = selected_model_id
                
                # Persist settings to user profile
                me_resp = api_request("GET", "/users/me")
                if me_resp and me_resp.status_code == 200:
                    user_id = me_resp.json().get("user_id")
                    update_payload = {
                        "default_model_id": selected_model_id,
                        "default_temperature": temperature,
                        "default_max_tokens": max_tokens if max_tokens > 0 else None,
                        "default_top_p": top_p,
                        "default_frequency_penalty": frequency_penalty,
                        "default_presence_penalty": presence_penalty,
                    }
                    api_request("PUT", f"/users/{user_id}", json=update_payload)
                
                st.success("Settings saved! These will be used as your default generation settings.")

        if st.button("🔄 Refresh Models List"):
            refresh_models()
            st.rerun()

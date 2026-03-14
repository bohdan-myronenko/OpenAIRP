import streamlit as st

from api_client import API_URL, PUBLIC_API_URL, api_request
from data_cache import load_personas, refresh_personas


def show_personas():
    """Personas management page."""
    st.header("👤 User Personas")

    tab1, tab2 = st.tabs(["📋 List Personas", "➕ Create Persona"])

    with tab1:
        st.subheader("Your Personas")
        personas = load_personas()

        if not personas:
            st.info("No personas found. Create one using the 'Create Persona' tab!")
        else:
            for persona in personas:
                persona_id = persona.get('persona_id')
                with st.expander(f"👤 {persona.get('name', 'Unnamed')} (ID: {persona_id})"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        avatar_url = persona.get('avatar_url')
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

                        st.write(f"**Name:** {persona.get('name', 'N/A')}")
                        desc = persona.get('description')
                        if desc:
                            st.write(f"**Description:** {desc}")
                        st.write(f"**Default:** {'Yes' if persona.get('is_default') else 'No'}")
                    with col2:
                        st.write(f"**Persona ID:** {persona_id}")

                        st.markdown("---")
                        if st.button("✏️ Edit Persona", key=f"edit_persona_{persona_id}"):
                            st.session_state[f"editing_persona_{persona_id}"] = True
                            st.rerun()

                        st.markdown("---")
                        st.write("**Upload Profile Picture**")
                        uploaded_file = st.file_uploader(
                            "Choose an image",
                            type=['jpg', 'jpeg', 'png', 'gif', 'webp'],
                            key=f"persona_avatar_{persona_id}"
                        )
                        if uploaded_file is not None:
                            if st.button(f"Upload", key=f"upload_persona_{persona_id}"):
                                files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
                                url = f"{API_URL}/personas/{persona_id}/avatar"
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
                                        refresh_personas()
                                        st.rerun()
                                    else:
                                        try:
                                            error_detail = response.json().get("detail", response.text)
                                        except Exception:
                                            error_detail = response.text
                                        st.error(f"Upload failed: {error_detail}")
                                except Exception as e:
                                    st.error(f"Error uploading file: {e}")

                        if st.button(f"Delete", key=f"delete_{persona_id}"):
                            response = api_request("DELETE", f"/personas/{persona_id}")
                            if response:
                                st.success("Persona deleted!")
                                refresh_personas()
                                st.rerun()

                    if st.session_state.get(f"editing_persona_{persona_id}", False):
                        st.markdown("---")
                        st.subheader("✏️ Edit Persona")
                        with st.form(f"edit_persona_form_{persona_id}"):
                            edit_name = st.text_input("Persona Name *", value=persona.get('name', ''), key=f"edit_persona_name_{persona_id}")
                            edit_description = st.text_area("Description", value=persona.get('description', '') or '', key=f"edit_persona_desc_{persona_id}")
                            edit_is_default = st.checkbox("Set as Default", value=persona.get('is_default', False), key=f"edit_persona_default_{persona_id}")

                            col_submit, col_cancel = st.columns(2)
                            with col_submit:
                                submitted = st.form_submit_button("💾 Save Changes", type="primary")
                            with col_cancel:
                                cancelled = st.form_submit_button("❌ Cancel")

                            if cancelled:
                                st.session_state[f"editing_persona_{persona_id}"] = False
                                st.rerun()

                            if submitted:
                                if not edit_name:
                                    st.error("Persona name is required!")
                                else:
                                    payload = {
                                        "name": edit_name,
                                        "description": edit_description if edit_description else None,
                                        "is_default": edit_is_default,
                                    }

                                    response = api_request("PUT", f"/personas/{persona_id}", json=payload)
                                    if response:
                                        st.success("Persona updated successfully!")
                                        st.session_state[f"editing_persona_{persona_id}"] = False
                                        refresh_personas()
                                        st.rerun()
                                    else:
                                        st.error("Failed to update persona. Please try again.")

            if st.button("🔄 Refresh Personas List"):
                refresh_personas()
                st.rerun()

    with tab2:
        st.subheader("Create New Persona")
        with st.form("create_persona_form"):
            name = st.text_input("Persona Name *", placeholder="Enter persona name")
            description = st.text_area("Description", placeholder="Enter persona description (optional)")
            is_default = st.checkbox("Set as Default", value=False)

            st.markdown("---")
            st.write("**Profile Picture (optional)**")
            st.caption("You can upload a profile picture after creating the persona, or upload it now and it will be set after creation.")
            avatar_file = st.file_uploader(
                "Choose an image",
                type=['jpg', 'jpeg', 'png', 'gif', 'webp'],
                key="create_persona_avatar"
            )

            submitted = st.form_submit_button("Create Persona", type="primary")

            if submitted:
                if not name:
                    st.error("Persona name is required!")
                else:
                    payload = {
                        "name": name,
                        "description": description if description else None,
                        "avatar_url": None,
                        "is_default": is_default,
                    }

                    response = api_request("POST", "/personas", json=payload)
                    if response:
                        persona_data = response.json()
                        persona_id = persona_data.get('persona_id')

                        if avatar_file is not None and persona_id:
                            files = {'file': (avatar_file.name, avatar_file, avatar_file.type)}
                            url = f"{API_URL}/personas/{persona_id}/avatar"
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
                                    st.success("Persona created and profile picture uploaded successfully!")
                                else:
                                    st.success("Persona created successfully! (Profile picture upload failed)")
                            except Exception as e:
                                st.success(f"Persona created successfully! (Profile picture upload error: {e})")
                        else:
                            st.success("Persona created successfully!")

                        refresh_personas()
                        st.rerun()

import streamlit as st
import pandas as pd
from api_client import api_get, api_post, api_put, api_delete

def fetch_models():
    try:
        return api_get("/models/admin/all")
    except Exception as e:
        st.error(f"Error fetching models: {e}")
        return []

def show_models():
    st.header("🤖 Model Management")
    st.markdown("Global models configured for your instance. Active models are available for users to use.")

    models = fetch_models()

    if models:
        # Display as a dataframe
        data = []
        for m in models:
            data.append({
                "ID": m.get("model_id"),
                "Name": m.get("name"),
                "Model Identifier": m.get("model_name"),
                "API URL": m.get("api_url"),
                "Active (Usable)": "✅" if m.get("is_active") else "❌"
            })
            
        st.dataframe(data, use_container_width=True)
    else:
        st.info("No models configured yet.")

    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Create New Model")
        with st.form("create_model_form", clear_on_submit=True):
            model_name = st.text_input("Name (Display Name) *")
            api_url = st.text_input("API URL *", help="E.g., https://api.openai.com/v1")
            api_key = st.text_input("API Key *", type="password")
            model_name_field = st.text_input("Model Identifier *", help="E.g., gpt-4, claude-3-opus")
            custom_prompt = st.text_area("Custom System Prompt (optional)")
            is_active = st.checkbox("Active (Usable by users)?", value=True)
            description = st.text_area("Description (optional)")
            
            submit = st.form_submit_button("Create Model", type="primary")
            if submit:
                if not model_name or not api_url or not api_key or not model_name_field:
                    st.error("Please fill in all required fields (marked with *).")
                else:
                    payload = {
                        "name": model_name,
                        "api_url": api_url,
                        "api_key": api_key,
                        "model_name": model_name_field,
                        "custom_prompt": custom_prompt if custom_prompt else None,
                        "is_active": is_active,
                        "description": description if description else None
                    }
                    try:
                        api_post("/models", payload)
                        st.success("Model created successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating model: {e}")

    with col2:
        st.subheader("Manage Existing Models")
        if models:
            model_options = {f"{m['name']} ({m['model_name']}) (ID: {m['model_id']})": m for m in models}
            selected_str = st.selectbox("Select Model to Edit or Delete", options=list(model_options.keys()))
            selected_model = model_options[selected_str]
            
            with st.expander("Edit Parameters"):
                with st.form("edit_model_form"):
                    edit_name = st.text_input("Name", value=selected_model.get("name", ""))
                    edit_api_url = st.text_input("API URL", value=selected_model.get("api_url", ""))
                    edit_api_key = st.text_input("API Key (leave blank to keep current)", type="password")
                    edit_model_name = st.text_input("Model Identifier", value=selected_model.get("model_name", ""))
                    edit_prompt = st.text_area("Custom Prompt", value=selected_model.get("custom_prompt") or "")
                    edit_desc = st.text_area("Description", value=selected_model.get("description") or "")
                    edit_active = st.checkbox("Active (Usable)", value=selected_model.get("is_active", False))
                    
                    update_btn = st.form_submit_button("Update Model")
                    if update_btn:
                        update_payload = {
                            "name": edit_name,
                            "api_url": edit_api_url,
                            "model_name": edit_model_name,
                            "custom_prompt": edit_prompt if edit_prompt else None,
                            "description": edit_desc if edit_desc else None,
                            "is_active": edit_active
                        }
                        if edit_api_key:
                            update_payload["api_key"] = edit_api_key
                            
                        try:
                            api_put(f"/models/{selected_model['model_id']}", update_payload)
                            st.success("Model updated successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating model: {e}")
            
            st.markdown("---")
            st.write("Delete Model")
            confirm_delete = st.checkbox(f"I understand this will permanently delete {selected_model['name']}.")
            if st.button("Delete Model", type="primary", disabled=not confirm_delete):
                try:
                    api_delete(f"/models/{selected_model['model_id']}")
                    st.success("Model deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting model: {e}")
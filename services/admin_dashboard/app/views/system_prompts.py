import streamlit as st
from api_client import api_get, api_post, api_put, api_delete

def fetch_system_prompts():
    try:
        data = api_get("/system-prompts")
        # Ensure we return an empty list if there's no data
        if not data:
            return []
        return data if isinstance(data, list) else []
    except Exception as e:
        st.error(f"Error fetching system prompts: {e}")
        return []

def show_system_prompts_manager():
    st.header("System Prompt Management")

    prompts = fetch_system_prompts()
    if prompts:
        prompt_data = []
        for p in prompts:
            prompt_data.append({
                "ID": p.get("prompt_id"),
                "Name": p.get("name"),
                "Active": "Yes" if p.get("is_active") else "No",
                "Description": p.get("description", "")
            })
        st.dataframe(prompt_data, use_container_width=True)
    else:
        st.info("No system prompts found.")

    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Create New System Prompt")
        with st.form("create_system_prompt", clear_on_submit=True):
            name = st.text_input("Name *")
            description = st.text_area("Description")
            content = st.text_area("Content (System Prompt) *", height=150)
            is_active = st.checkbox("Set as Active", value=False)
            submit = st.form_submit_button("Create")
            
            if submit:
                if not name or not content:
                    st.error("Name and Content are required!")
                else:
                    payload = {
                        "name": name,
                        "description": description if description else None,
                        "content": content,
                        "is_active": is_active
                    }
                    try:
                        api_post("/system-prompts", payload)
                        st.success("System prompt created successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating system prompt: {e}")
                        
    with col2:
        st.subheader("Edit / Delete System Prompt")
        if prompts:
            prompt_options = {f"{p['prompt_id']} - {p['name']}": p for p in prompts}
            selected_prompt_str = st.selectbox("Select System Prompt", options=list(prompt_options.keys()))
            selected_prompt = prompt_options[selected_prompt_str]
            
            with st.form("edit_system_prompt"):
                e_name = st.text_input("Name *", value=selected_prompt.get("name", ""))
                e_description = st.text_area("Description", value=selected_prompt.get("description", "") or "")
                e_content = st.text_area("Content (System Prompt) *", value=selected_prompt.get("content", ""), height=150)
                e_is_active = st.checkbox("Set as Active", value=selected_prompt.get("is_active", False))
                
                update_btn = st.form_submit_button("Update System Prompt")
                if update_btn:
                    if not e_name or not e_content:
                        st.error("Name and Content are required!")
                    else:
                        payload = {
                            "name": e_name,
                            "description": e_description if e_description else None,
                            "content": e_content,
                            "is_active": e_is_active
                        }
                        try:
                            api_put(f"/system-prompts/{selected_prompt['prompt_id']}", payload)
                            st.success("System prompt updated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating system prompt: {e}")
            
            if st.button("Delete Selected System Prompt"):
                try:
                    api_delete(f"/system-prompts/{selected_prompt['prompt_id']}")
                    st.success("System prompt deleted!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting system prompt: {e}")

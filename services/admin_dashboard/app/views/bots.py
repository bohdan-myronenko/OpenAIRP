import streamlit as st
from api_client import api_get, api_post, api_put, api_delete
import json

def fetch_bots():
    try:
        return api_get("/bots")
    except Exception as e:
        st.error(f"Error fetching bots: {e}")
        return []

def show_bots_manager():
    st.header("Bot Management")

    bots = fetch_bots()
    if bots:
        bot_data = []
        for b in bots:
            bot_data.append({
                "ID": b.get("bot_id"),
                "Name": b.get("name"),
                "Description": b.get("description", ""),
                "Tags": ", ".join(b.get("tags", []))
            })
        st.dataframe(bot_data, use_container_width=True)
    else:
        st.info("No bots found.")

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("Create New Bot")
        with st.form("create_bot", clear_on_submit=True):
            name = st.text_input("Name *")
            title = st.text_input("Title (optional, defaults to Name)")
            description = st.text_area("Description")
            persona = st.text_area("Persona", help="Use {{char}} and {{user}}")
            scenario = st.text_area("Scenario")
            greeting = st.text_area("Greeting")
            example_dialog = st.text_area("Example Dialog")
            tags = st.text_input("Tags (comma separated)")
            submit = st.form_submit_button("Create")
            
            if submit:
                if not name:
                    st.error("Name is required!")
                else:
                    payload = {
                        "name": name,
                        "title": title if title else name,
                        "description": description if description else None,
                        "persona": persona,
                        "scenario": scenario if scenario else None,
                        "greeting": greeting if greeting else None,
                        "example_dialog": example_dialog if example_dialog else None,
                        "tags": [t.strip() for t in tags.split(",") if t.strip()]
                    }
                    try:
                        api_post("/bots", payload)
                        st.success("Bot created successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating bot: {e}")
                        
    with col2:
        st.subheader("Edit / Delete Bot")
        if bots:
            bot_options = {f"{b['bot_id']} - {b['name']}": b for b in bots}
            selected_bot_str = st.selectbox("Select Bot", options=list(bot_options.keys()))
            selected_bot = bot_options[selected_bot_str]
            
            with st.form("edit_bot"):
                e_name = st.text_input("Name *", value=selected_bot.get("name", ""))
                e_title = st.text_input("Title", value=selected_bot.get("title", ""))
                e_description = st.text_area("Description", value=selected_bot.get("description", "") or "")
                e_persona = st.text_area("Persona", value=selected_bot.get("persona", "") or "")
                e_scenario = st.text_area("Scenario", value=selected_bot.get("scenario", "") or "")
                e_greeting = st.text_area("Greeting", value=selected_bot.get("greeting", "") or "")
                e_example_dialog = st.text_area("Example Dialog", value=selected_bot.get("example_dialog", "") or "")
                e_tags = st.text_input("Tags (comma separated)", value=", ".join(selected_bot.get("tags", [])))
                
                update_btn = st.form_submit_button("Update Bot")
                if update_btn:
                    if not e_name:
                        st.error("Name is required!")
                    else:
                        payload = {
                            "name": e_name,
                            "title": e_title if e_title else e_name,
                            "description": e_description if e_description else None,
                            "persona": e_persona,
                            "scenario": e_scenario if e_scenario else None,
                            "greeting": e_greeting if e_greeting else None,
                            "example_dialog": e_example_dialog if e_example_dialog else None,
                            "tags": [t.strip() for t in e_tags.split(",") if t.strip()]
                        }
                        try:
                            api_put(f"/bots/{selected_bot['bot_id']}", payload)
                            st.success("Bot updated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating bot: {e}")
            
            if st.button("Delete Selected Bot"):
                try:
                    api_delete(f"/bots/{selected_bot['bot_id']}")
                    st.success("Bot deleted!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error deleting bot: {e}")
                    
    with col3:
        st.subheader("Import JSONL")
        uploaded_file = st.file_uploader("Upload JSONL File", type=["jsonl"])
        if uploaded_file is not None:
            if st.button("Import Bots"):
                success_count = 0
                error_count = 0
                content = uploaded_file.getvalue().decode("utf-8").splitlines()
                for line in content:
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        bot_name = data.get("bot_name", "").strip()
                        if not bot_name:
                            error_count += 1
                            continue
                        
                        payload = {
                            "name": bot_name,
                            "title": bot_name,
                            "persona": data.get("bot_persona", "").strip(),
                            "scenario": data.get("Scenario", "").strip() or None,
                            "example_dialog": data.get("example_dialogs", "").strip() or None,
                            "greeting": data.get("Intro", "").strip() or None,
                            "description": None,
                            "tags": []
                        }
                        api_post("/bots", payload)
                        success_count += 1
                    except Exception:
                        error_count += 1
                
                st.success(f"Import complete! {success_count} succeeded, {error_count} failed.")
                st.rerun()

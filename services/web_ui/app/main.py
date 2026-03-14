from auth import init_authenticator
from state import init_page_config, init_session_state
from app import main

init_page_config()
init_session_state()
init_authenticator()


if __name__ == "__main__":
    main()

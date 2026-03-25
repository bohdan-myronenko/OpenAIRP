import os
import requests

API_URL = os.getenv("API_URL", "http://api:8080")
DEFAULT_TIMEOUT = 30

def get_admin_auth():
    """Returns the basic auth tuple for the admin user defined in env."""
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if username and password:
        return (username, password)
    return None

def api_get(endpoint):
    url = f"{API_URL}{endpoint}"
    response = requests.get(url, auth=get_admin_auth(), timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if response.status_code == 204:
        return []
    return response.json()

def api_post(endpoint, json_data):
    url = f"{API_URL}{endpoint}"
    response = requests.post(url, json=json_data, auth=get_admin_auth(), timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if response.status_code == 204:
        return {}
    return response.json()

def api_put(endpoint, json_data):
    url = f"{API_URL}{endpoint}"
    response = requests.put(url, json=json_data, auth=get_admin_auth(), timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if response.status_code == 204:
        return {}
    return response.json()

def api_delete(endpoint):
    url = f"{API_URL}{endpoint}"
    response = requests.delete(url, auth=get_admin_auth(), timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except:
        return {}

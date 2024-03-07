from firebase_functions import https_fn
from firebase_admin import initialize_app, auth
import requests
import os

initialize_app()

api_key = os.environ.get('ELEVEN_LABS_API_KEY', '')

@https_fn.on_request()
def proxy_eleven(request: https_fn.Request) -> https_fn.Response:
    test_token = os.environ.get('TEST_TOKEN', '')
    auth_header = request.headers.get('Authorization')
    if auth_header:
        id_token = auth_header.split('Bearer ')[1]
    else:
        id_token = None

    if os.environ.get('ENV') == 'production' & id_token != test_token:
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']
        except ValueError:
            return https_fn.Response("Unauthorized", status=401)
        
    base_api_url = "https://api.elevenlabs.io/v1"
    api_url = f"{base_api_url}{request.path}"
    headers = {
        "xi-api-key": api_key,
        "content-type": "application/json",
    }
    headers.pop('host', None)
    print(f"Proxy to: {api_url}")

    try:
        if request.method == 'GET':
            api_response = requests.get(api_url, headers=headers)
        elif request.method == 'POST':
            api_response = requests.post(api_url, headers=headers, json=request.get_json())
        else:
            return https_fn.Response(f"Method {request.method} not supported", status=405)

        return https_fn.Response(api_response.text, status=api_response.status_code, headers=api_response.headers.items())

    except requests.RequestException as e:
        print(f"Error calling ElevenLabs API: {str(e)}")
        return https_fn.Response("Error processing your request.", status=500)
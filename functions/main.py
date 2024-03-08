from firebase_functions import https_fn
from firebase_admin import initialize_app, auth
from mux_python import PlaybackPolicy, ApiClient, AssetsApi, Configuration, DirectUploadsApi, CreateUploadRequest, CreateAssetRequest
from mux_python.rest import ApiException
import requests
import os
import tempfile
import base64
import json

initialize_app()

api_key = os.environ.get('ELEVEN_LABS_API_KEY', '')

configuration = Configuration()
configuration.username = os.environ.get('MUX_TOKEN_ID', '')
configuration.password = os.environ.get('MUX_TOKEN_SECRET', '')
uploads_api = DirectUploadsApi(ApiClient(configuration))
assets_api = AssetsApi(ApiClient(configuration))

@https_fn.on_request()
def proxy_eleven(request: https_fn.Request) -> https_fn.Response:
    test_token = os.environ.get('TEST_TOKEN', '')
    auth_header = request.headers.get('Authorization')
    if auth_header:
        id_token = auth_header.split('Bearer ')[1]
    else:
        id_token = None

    if os.environ.get('ENV') == 'production' and id_token != test_token:
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
            if 'text-to-speech' in request.path:
                api_response = requests.post(api_url, headers=headers, json=request.get_json(), stream=True)

                if api_response.headers['Content-Type'] == 'audio/mpeg':
                    with tempfile.NamedTemporaryFile(delete=False) as fp:
                        for chunk in api_response.iter_content(chunk_size=8192):
                            if chunk:
                                fp.write(chunk)

                    with open(fp.name, 'rb') as file:
                        base64_audio = base64.b64encode(file.read()).decode()

                    response = json.dumps({'audio': base64_audio})

                    return https_fn.Response(response, status=200, headers={'Content-Type': 'application/json'})
                else:
                    return https_fn.Response(api_response.text, status=api_response.status_code, headers=api_response.headers.items())

            else:
                api_response = requests.post(api_url, headers=headers, json=request.get_json())

        else:
            return https_fn.Response(f"Method {request.method} not supported", status=405)

        return https_fn.Response(api_response.text, status=api_response.status_code, headers=api_response.headers.items())

    except requests.RequestException as e:
        print(f"Error calling ElevenLabs API: {str(e)}")
        return https_fn.Response("Error processing your request.", status=500)

def mux_upload(fp) -> https_fn.Response:
    try: 
        create_asset_request = CreateAssetRequest(playback_policy=[PlaybackPolicy.PUBLIC])
        create_upload_request = CreateUploadRequest(timeout=3600, new_asset_settings=create_asset_request)
        create_upload_response = uploads_api.create_direct_upload(create_upload_request)
        upload_url = create_upload_response.data.url
        with open(fp.name, 'rb') as file:
            requests.put(upload_url, data=file)
    except ApiException as e:
        print(f"Exception when calling DirectUploadsApi->create_direct_upload: {str(e)}")
        return https_fn.Response("Error processing your request.", status=500)
    
    try: 
        asset_id = create_upload_response.data.asset_id
        asset = assets_api.get_asset(asset_id)
        streaming_url = asset.data.playback_urls.master.url
    except ApiException as e:
        print(f"Exception when calling AssetsApi->get_asset: {str(e)}")
        return https_fn.Response("Error processing your request.", status=500)
    
    return https_fn.Response(streaming_url, status=200)

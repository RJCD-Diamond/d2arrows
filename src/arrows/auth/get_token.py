import argparse
import base64
import datetime
import hashlib
import json
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pprint import pprint
from typing import Any

import requests

PORT = "5173"


# dev
DEV_CLIENT_ID = "workflows-ui-dev"
DEV_AUTHORIZE_URL = (
    "https://identity-dev.diamond.ac.uk/realms/dls/protocol/openid-connect/auth"
)
DEV_TOKEN_URL = (
    "https://identity-dev.diamond.ac.uk/realms/dls/protocol/openid-connect/token"
)


# prod
PROD_CLIENT_ID = "workflows-dashboard"
PROD_AUTHORIZE_URL = (
    "https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/auth"
)
PROD_TOKEN_URL = (
    "https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/token"
)


def get_token(
    username: str | None = None,
    password: str | None = None,
    decode_token: bool = False,
    dev: bool = False,
) -> str | dict[str, Any]:
    if dev:
        client_id = DEV_CLIENT_ID
        authorize_url = DEV_AUTHORIZE_URL
        token_url = DEV_TOKEN_URL
    else:
        client_id = PROD_CLIENT_ID
        authorize_url = PROD_AUTHORIZE_URL
        token_url = PROD_TOKEN_URL

    redirect_uri = f"http://localhost:{PORT}"
    scope = "openid posix-uid profile email fedid"
    client_secret = ""
    # Step 1: Generate PKCE code verifier and challenge
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode("utf-8").rstrip("=")
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    # Step 2: Build authorization URL
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{authorize_url}?{urllib.parse.urlencode(params)}"

    print("Opening browser for user login...")
    webbrowser.open(auth_url)

    # Step 3: Start local HTTP server to capture redirect with code
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            if "code" in params:
                self.server.auth_code = params["code"][0]  # type: ignore
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"Authorization successful. You can close this window."
                )
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing authorization code.")

    httpd = HTTPServer(("localhost", int(PORT)), CallbackHandler)
    httpd.handle_request()  # Wait for one request
    auth_code = httpd.auth_code  # type: ignore

    # print("Authorization code received:", auth_code)

    # Step 4: Exchange code for token
    if client_secret:
        token_resp = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            auth=(client_id, client_secret),
        )
    else:
        # basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        token_resp = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "client_id": client_id,
            },
        )
    pprint(token_resp.json())
    token_resp.raise_for_status()
    token_data = token_resp.json()

    print("Access Token:", token_data.get("access_token"))
    # print("Refresh Token:", token_data.get("refresh_token", "N/A"))
    # pprint(_decode_inner(token_data))

    if decode_token:
        return _decode_inner(token_data)

    else:
        return token_data.get("access_token", "")


def _decode_inner(token: dict[str, Any]) -> dict[str, Any]:
    def decode(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return _jwt_decode(value)
            except Exception:
                pass
            try:
                decoded_value = _b64url_decode(value)
                try:
                    return json.loads(decoded_value)
                except Exception:
                    return decoded_value
            except Exception:
                pass
        return value

    return {k: decode(v) for k, v in token.items()}


def _b64url_decode(data: str) -> str:
    # Add required padding (=) if missing
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode()


def _jwt_decode(jwt: str) -> dict[str, Any]:
    header_b64, payload_b64, signature_b64 = jwt.split(".")
    header = _convert_exp(json.loads(_b64url_decode(header_b64)))
    payload = _convert_exp(json.loads(_b64url_decode(payload_b64)))
    return {
        "jwt_header": header,
        "jwt_payload": payload,
        "jwt_signature": signature_b64,
    }


def _convert_exp(value: dict[str, Any]) -> dict[str, Any]:
    def convert(k: str, v: Any) -> Any:
        if k == "exp" or k == "iat":
            try:
                return datetime.datetime.fromtimestamp(float(v))
            except Exception:
                pass
        return v

    return {k: convert(k, v) for k, v in value.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dev", help="Get a token from identity-dev.", action="store_true"
    )
    args = parser.parse_args()
    print(get_token(dev=args.dev))


if __name__ == "__main__":
    main()

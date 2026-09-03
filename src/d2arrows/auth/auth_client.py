import base64
import datetime
import hashlib
import json
import os
import urllib.parse
import warnings
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import requests

PROD_IDENTITY = "identity"
PROD_CLIENT_ID = "workflows-dashboard"
# PROD_CLIENT_ID = "workflows-cli"

DEV_CLIENT_ID = "workflows-ui-dev"
DEV_IDENTITY = "identity-dev"


def _b64url_decode(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode()


def _convert_exp(value: dict[str, Any]) -> dict[str, Any]:
    def convert(k: str, v: Any) -> Any:
        if k in ("exp", "iat"):
            try:
                return datetime.datetime.fromtimestamp(float(v))
            except Exception:
                pass
        return v

    return {k: convert(k, v) for k, v in value.items()}


def decode_jwt(jwt: str) -> dict[str, Any]:
    header_b64, payload_b64, signature_b64 = jwt.split(".")
    header = _convert_exp(json.loads(_b64url_decode(header_b64)))
    payload = _convert_exp(json.loads(_b64url_decode(payload_b64)))
    return {
        "jwt_header": header,
        "jwt_payload": payload,
        "jwt_signature": signature_b64,
    }


def decode_token_data(token: dict[str, Any]) -> dict[str, Any]:
    def decode(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return decode_jwt(value)
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


def _token_expiry(access_token: str) -> datetime.datetime | None:
    """Extract the expiry time from a JWT access token."""
    try:
        _, payload_b64, _ = access_token.split(".")
        payload = json.loads(_b64url_decode(payload_b64))
        exp = payload.get("exp")
        if exp:
            return datetime.datetime.fromtimestamp(float(exp))
    except Exception:
        pass
    return None


def _browser_available() -> bool:
    """Return True if a browser can be opened in this environment."""
    try:
        controller = webbrowser.get()
        # In headless environments webbrowser.get() may return a GenericBrowser
        # backed by a command that doesn't exist (e.g. 'xdg-open' with no DISPLAY).
        # Checking DISPLAY/WAYLAND_DISPLAY on Linux catches the common CI/SSH case.
        if os.name == "posix":
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                return False
        return controller is not None
    except webbrowser.Error:
        return False


# ---------------------------------------------------------------------------
# TokenClient
# ---------------------------------------------------------------------------


class TokenClient:
    """
    OIDC token client supporting both browser-based PKCE flow and
    client credentials flow (e.g. Kubernetes service accounts).

    Parameters
    ----------
    dev:
        When True, targets the identity-dev realm and uses the dev client ID.
    port:
        Local port used as the PKCE redirect URI callback.
    cache_dir:
        Directory for the on-disk token cache. Defaults to
        ``~/.cache/dls_auth``.
    expiry_buffer_seconds:
        How many seconds before a token's actual expiry it is considered
        stale and will be refreshed.
    """

    _SCOPE = "openid posix-uid profile email fedid"

    def __init__(
        self,
        *,
        dev: bool = False,
        port: int = 5173,
        cache_dir: Path | None = None,
        expiry_buffer_seconds: int = 30,
    ) -> None:
        self.dev = dev
        self.port = port
        self.expiry_buffer_seconds = expiry_buffer_seconds

        self._cache_dir = cache_dir or Path.home() / ".cache" / "dls_auth"
        self._cache_file = self._cache_dir / "token_cache.json"

        ident = DEV_IDENTITY if dev else PROD_IDENTITY
        self.client_id = DEV_CLIENT_ID if dev else PROD_CLIENT_ID
        self.base = f"https://{ident}.diamond.ac.uk/realms/dls/protocol/openid-connect"
        self.token_url = f"{self.base}/token"
        self.authorize_url = f"{self.base}/auth"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_token(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> str:
        """Return a raw access token string."""
        token_data = self.get_token_data(
            client_id=client_id,
            client_secret=client_secret,
            decode_token=False,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        return token_data.get("access_token", "")

    def get_token_data(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        decode_token: bool = False,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Obtain an access token, using the local cache where possible.

        Parameters
        ----------
        client_id, client_secret:
            When both are provided, the client credentials flow is used.
            Both should come from environment variables / k8s secrets
            (``OIDC_CLIENT_ID``, ``OIDC_CLIENT_SECRET``).
        decode_token:
            Return the fully decoded token dict rather than the raw response.
        use_cache:
            Read from / write to the on-disk token cache.
        force_refresh:
            Ignore a valid cached token and fetch a new one.
        """
        token_data: dict | None = None

        # 1. Try the cache
        if use_cache and not force_refresh:
            cached_token = self._load_cached_token()
            if cached_token is not None and self._is_token_valid(cached_token):
                # print("Using cached token.")
                token_data = cached_token

        # 2. Fetch a fresh token
        if token_data is None:
            if client_id and client_secret:
                print("Fetching token via client credentials...")
                token_data = self._fetch_token_client_credentials(
                    client_id, client_secret
                )
            else:
                token_data = self._fetch_token_pkce()

        if use_cache:
            self._save_token_to_cache(token_data)

        return decode_token_data(token_data) if decode_token else token_data

    def clear_cache(self) -> None:
        """Remove the cached token for this environment (dev or prod)."""
        if not self._cache_file.exists():
            return
        try:
            data = json.loads(self._cache_file.read_text())
            data.pop(self._cache_key, None)
            self._cache_file.write_text(json.dumps(data, indent=2))
            env = "dev" if self.dev else "prod"
            print(f"Token cache cleared for {env}.")
        except Exception as exc:
            print(f"Warning: could not clear token cache — {exc}")

    def clear_all_caches(self) -> None:
        """Wipe the entire cache file regardless of environment."""
        if self._cache_file.exists():
            self._cache_file.unlink()
            print("Token cache cleared.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @property
    def _cache_key(self) -> str:
        return "dev" if self.dev else "prod"

    @property
    def _redirect_uri(self) -> str:
        return f"http://localhost:{self.port}"

    def _is_token_valid(self, token_data: dict) -> bool:
        access_token = token_data.get("access_token", "")
        if not access_token:
            return False

        expiry = _token_expiry(access_token)
        if expiry is None:
            cached_at = token_data.get("_cached_at")
            expires_in = token_data.get("expires_in")
            if cached_at and expires_in:
                cached_time = datetime.datetime.fromisoformat(cached_at)
                expiry = cached_time + datetime.timedelta(seconds=int(expires_in))
            else:
                return False

        return datetime.datetime.now() < (
            expiry - datetime.timedelta(seconds=self.expiry_buffer_seconds)
        )

    def _load_cached_token(self) -> dict | None:
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text())
                return data.get(self._cache_key)
        except Exception:
            pass
        return None

    def _save_token_to_cache(self, token_data: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            existing: dict = {}
            if self._cache_file.exists():
                try:
                    existing = json.loads(self._cache_file.read_text())
                except Exception:
                    pass
            to_save = {**token_data, "_cached_at": datetime.datetime.now().isoformat()}
            existing[self._cache_key] = to_save
            self._cache_file.write_text(json.dumps(existing, indent=2))
        except Exception as exc:
            print(f"Warning: could not save token cache — {exc}")

    def _build_pkce_params(self) -> tuple[str, str, str]:
        """Return (code_verifier, code_challenge, auth_url)."""
        code_verifier = (
            base64.urlsafe_b64encode(os.urandom(40)).decode("utf-8").rstrip("=")
        )
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self._redirect_uri,
            "scope": self._SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{self.authorize_url}?{urllib.parse.urlencode(params)}"
        return code_verifier, code_challenge, auth_url

    def _wait_for_auth_code(self) -> str:
        """Start a local HTTP server and block until the OIDC callback arrives."""

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):

                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=DeprecationWarning)
                    query = urllib.parse.urlparse(self.path).query
                    qs_params = urllib.parse.parse_qs(query)

                if "code" in qs_params:
                    self.server.auth_code = qs_params["code"][0]  # type: ignore[attr-defined]
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(
                        b"Authorization successful. You can close this window."
                    )
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Missing authorization code.")

            def log_message(self, format, *args):  # noqa: A002
                pass  # suppress request logging

        httpd = HTTPServer(("localhost", self.port), CallbackHandler)
        httpd.handle_request()
        return httpd.auth_code  # type: ignore[attr-defined]

    def _exchange_code_for_token(self, auth_code: str, code_verifier: str) -> dict:
        """Exchange an authorisation code for a token response."""
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
                "client_id": self.client_id,
            },
        )
        response.raise_for_status()
        return response.json()

    def _fetch_token_pkce(self) -> dict:
        """
        PKCE flow with automatic browser-open where possible, falling back
        to printing a clickable URL for headless / SSH environments.
        """
        code_verifier, _code_challenge, auth_url = self._build_pkce_params()

        if _browser_available():
            print("Opening browser for user login...")
            webbrowser.open(auth_url)
        else:
            print(
                "No browser detected. Open the following URL to authenticate:\n"
                f"\n    {auth_url}\n"
            )

        print(f"Waiting for authorisation callback on port {self.port}...")
        auth_code = self._wait_for_auth_code()
        return self._exchange_code_for_token(auth_code, code_verifier)

    def _fetch_token_client_credentials(
        self, client_id: str, client_secret: str
    ) -> dict:
        """Client credentials flow for service accounts."""
        response = requests.post(
            self.token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Convenience: default prod client (mirrors original module-level behaviour)
# ---------------------------------------------------------------------------

_default_client = TokenClient()


def get_token(**kwargs) -> str:
    """Module-level convenience wrapper using the default prod client."""
    return _default_client.get_token(**kwargs)


def get_json_header(**kwargs) -> str:
    """Return a dict suitable for use as an HTTP Authorization header."""
    token = _default_client.get_token(**kwargs)
    dict_header = {"Authorization": f"Bearer {token}"}
    json_header = json.dumps(dict_header)  # ensure serializable
    return json_header


if __name__ == "__main__":
    # _default_client.clear_cache()

    print(get_token())
    print(get_json_header())

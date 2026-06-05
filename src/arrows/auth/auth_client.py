# from keycloak.keycloak_openid import KeycloakOpenID
import json
import subprocess
from functools import cached_property
from typing import Any

import requests

# auth_provider = "authn" #ident
AUTH_PROVIDER = "identity"  # ident
WELL_KNOWN_URL_FORMAT = (
    "https://{}.diamond.ac.uk/realms/dls/.well-known/openid-configuration"
)
WELL_KNOWN_URL = WELL_KNOWN_URL_FORMAT.format(AUTH_PROVIDER)


class AuthClient:
    def __init__(self, well_known_url=WELL_KNOWN_URL):

        self.well_known_url = well_known_url

    @cached_property
    def oidc_configuration(self) -> dict:
        response = self._get_to_json(self.well_known_url)
        return response

    def list_reponse(self) -> None:
        print("Endpoints:")
        for k, v in self.oidc_configuration.items():
            print(k, ":", v)

    def _get_to_json(self, url: str) -> dict[str, Any]:
        r = requests.get(url)
        r.raise_for_status()
        return r.json()

    @cached_property
    def issuer(self) -> str:
        issuer = self.oidc_configuration.get("issuer")
        # print("issuer", issuer)
        assert issuer is not None
        # https://identity.diamond.ac.uk/realms/dls
        return issuer

    @cached_property
    def authorization_endpoint(self) -> str:
        authorization_endpoint = self.oidc_configuration.get("authorization_endpoint")
        print("authorization_endpoint", authorization_endpoint)
        assert authorization_endpoint is not None
        return authorization_endpoint

    @cached_property
    def grant_types_supported(self) -> list[str] | None:
        grant_types_supported = self.oidc_configuration.get("grant_types_supported")
        print("grant_types_supported", grant_types_supported)
        return grant_types_supported

    @cached_property
    def token_endpoint(self) -> str:
        token_endpoint = self.oidc_configuration.get("token_endpoint")
        print("token_endpoint", token_endpoint)
        assert token_endpoint is not None

        # https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/token
        return token_endpoint

    @cached_property
    def device_authorization_endpoint(self) -> str:
        device_authorization_endpoint = self.oidc_configuration.get(
            "device_authorization_endpoint"
        )
        print("device_authorization_endpoint", device_authorization_endpoint)
        assert device_authorization_endpoint is not None

        # https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/auth/device
        return device_authorization_endpoint

    @cached_property
    def jwks_uri(self) -> str:
        jwks_uri = self.oidc_configuration.get("jwks_uri")
        print("jwks_uri", jwks_uri)
        assert jwks_uri is not None
        return jwks_uri

    def get_specific_auth_token(self, issuer: str, oidc_client_id: str) -> str:
        cmd: list[str] = [
            "kubectl",
            "oidc-login",
            "get-token",
            f"--oidc-issuer-url={issuer}",
            f"--oidc-client-id={oidc_client_id}",
            "--grant-type=authcode",
            "--listen-address=localhost:5173",
            "--skip-open-browser",
        ]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        out_lines: list[str] = []
        assert proc.stdout is not None
        for ln in proc.stdout:
            print(ln, end="")
            out_lines.append(ln)
        rc = proc.wait()
        out = "".join(out_lines)

        if rc:
            raise RuntimeError(f"kubectl exited {rc}; output:\n{out}")
        try:
            return json.loads(out)["status"]["token"]
        except Exception as e:
            raise RuntimeError(f"failed to parse token: {e}\nOutput:\n{out}") from e

    def get_authn_token(self) -> str:
        # command = "kubectl oidc-login get-token --oidc-issuer-url=https://authn.diamond.ac.uk/realms/master --oidc-client-id=visr-app-dev --grant-type=password --oidc-use-access-token | jq -r '.status.token'" #noqa

        token = self.get_specific_auth_token(
            issuer="https://authn.diamond.ac.uk/realms/master",
            oidc_client_id="visr-app-dev",
        )

        return token

    def get_client_auth_token(self, oidc_client_id: str) -> str:
        return self.get_specific_auth_token(
            issuer=self.issuer, oidc_client_id=oidc_client_id
        )

    def get_auth_token(self) -> str:

        ### except this logs in the user and opens a browser window,
        # so not ideal for a client library.
        # But it is the only way I have found to get a token without having to set up a
        # client secret or use the password grant type, which is not recommended.

        return self.get_specific_auth_token(
            issuer=self.issuer, oidc_client_id="workflows-dashboard"
        )


if __name__ == "__main__":
    client = AuthClient()
    # client.list_reponse()
    token = client.get_auth_token()
    print("Token:", token)

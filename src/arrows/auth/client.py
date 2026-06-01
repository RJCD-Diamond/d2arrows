import requests
import subprocess
# from keycloak.keycloak_openid import KeycloakOpenID
import json
from functools import cached_property

# auth_provider = "authn" #ident
AUTH_PROVIDER = "identity" #ident
WELL_KNOWN_URL_FORMAT = "https://{}.diamond.ac.uk/realms/dls/.well-known/openid-configuration"
WELL_KNOWN_URL = WELL_KNOWN_URL_FORMAT.format(AUTH_PROVIDER)


class OIDCClient:

    def __init__(self, well_known_url=WELL_KNOWN_URL):

        self.well_known_url = well_known_url

    @cached_property
    def oidc_configuration(self) -> dict:
        response = self._get_to_json(self.well_known_url)
        return response
    
    def list_reponse(self):
        print("Endpoints:")
        for k, v in self.oidc_configuration.items():
            print(k, ":", v)
    
    def _get_to_json(self, url):
        r = requests.get(url)
        r.raise_for_status()
        return r.json()
    
    @cached_property
    def issuer(self) -> str:
        issuer = self.oidc_configuration.get("issuer")
        print("issuer", issuer)
        # https://identity.diamond.ac.uk/realms/dls
        return issuer

    @cached_property
    def authorization_endpoint(self):
        authorization_endpoint = self.oidc_configuration.get("authorization_endpoint")
        print("authorization_endpoint", authorization_endpoint)
        # https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/auth
        return authorization_endpoint
    
    @cached_property
    def grant_types_supported(self):
        grant_types_supported = self.oidc_configuration.get("grant_types_supported")
        print("grant_types_supported", grant_types_supported)
        return grant_types_supported

    @cached_property
    def token_endpoint(self) -> str:
        token_endpoint = self.oidc_configuration.get("token_endpoint")
        print("token_endpoint", token_endpoint)
        # https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/token
        return token_endpoint
    
    
    @cached_property
    def device_authorization_endpoint(self) -> str:
        device_authorization_endpoint = self.oidc_configuration.get("device_authorization_endpoint")
        print("device_authorization_endpoint", device_authorization_endpoint)
        # https://identity.diamond.ac.uk/realms/dls/protocol/openid-connect/auth/device
        return device_authorization_endpoint


    @cached_property
    def jwks_uri(self):
        jwks_uri = self.oidc_configuration.get("jwks_uri")
        print("jwks_uri", jwks_uri)
        return jwks_uri
    
    def get_specific_auth_token(self, issuer: str, oidc_client_id: str):

        cmd = [
            "kubectl",
            "oidc-login",
            "get-token",
            f"--oidc-issuer-url={issuer}",
            f"--oidc-client-id={oidc_client_id}",
            "--grant-type=authcode",
            "--listen-address=localhost:5173",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)["status"]["token"]

    def get_authn_token(self):
        # command = "kubectl oidc-login get-token --oidc-issuer-url=https://authn.diamond.ac.uk/realms/master --oidc-client-id=visr-app-dev --grant-type=password --oidc-use-access-token | jq -r '.status.token'"

        token = self.get_specific_auth_token(issuer="https://authn.diamond.ac.uk/realms/master", oidc_client_id="visr-app-dev")

        return token
    
    def get_client_auth_token(self, oidc_client_id):

        token = self.get_specific_auth_token(issuer=self.issuer, oidc_client_id=oidc_client_id)
        
        return token


    def get_auth_token(self):

        ### except this logs in the user and opens a browser window, 
        # so not ideal for a client library. 
        # But it is the only way I have found to get a token without having to set up a 
        # client secret or use the password grant type, which is not recommended.

        token = self.get_specific_auth_token(issuer=self.issuer, oidc_client_id="workflows-dashboard")
        
        return token
    
if __name__ == "__main__":
    client = OIDCClient()
    client.list_reponse()
    token = client.get_auth_token()
    print("Token:", token)

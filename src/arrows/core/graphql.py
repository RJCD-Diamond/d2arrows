import requests

from arrows.auth.auth_client import TokenClient


class GraphQLError(Exception):
    """Raised when the GraphQL response contains errors."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        messages = "; ".join(e.get("message", str(e)) for e in errors)
        super().__init__(f"GraphQL error(s): {messages}")


class BaseGraphqlClient:
    def __init__(
        self,
        url: str,
        timeout: int = 30,
        dev: bool = False,
    ):
        """
        Args:
            url:     Full GraphQL endpoint URL, e.g. "https://api.example.com/graphql"
            timeout: Request timeout in seconds.
        """

        self.url = url
        self.timeout = timeout
        self.token_client = TokenClient(dev=dev)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.set_auth_header(self.token_client.get_token())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_query(self, query: str, variables: dict | None = None) -> dict:
        self.refresh_token_if_needed()

        response = self.session.post(
            self.url,
            json={"query": query, "variables": variables or {}},
            timeout=self.timeout,
        )

        # If the server still rejects the token (e.g. it was revoked server-side),
        # force a fresh token and retry once before giving up.
        if response.status_code == 401:
            self.set_auth_header(self.token_client.get_token(force_refresh=True))
            response = self.session.post(
                self.url,
                json={"query": query, "variables": variables or {}},
                timeout=self.timeout,
            )

        response.raise_for_status()

        body = response.json()

        if errors := body.get("errors"):
            raise GraphQLError(errors)

        return body.get("data", {})

    def set_auth_header(self, token: str) -> None:
        self.session.headers["Authorization"] = f"Bearer {token}"

    def refresh_token_if_needed(self) -> None:
        """Proactively refresh the token before each request if it has expired."""
        self.set_auth_header(self.token_client.get_token())

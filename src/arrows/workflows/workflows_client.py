"""
GraphQL client for workflow queries and mutations.

Usage:
    client = WorkflowClient(url="https://your-graphql-endpoint", token="your-token")

    # List workflow templates
    templates = client.get_workflow_templates(science_group="IMAGING", limit=5)

    # Get filtered workflows for a visit
    workflows = client.get_workflows(
        proposal_code="mg", proposal_number=36964, visit_number=1,
        creator="gmg29649", template="example-template", succeeded=True
    )

    # Get a specific workflow
    workflow = client.get_workflow(
        proposal_code="mg", proposal_number=36964, visit_number=1,
        name="conditional-steps-tswxm"
    )

    # Submit a workflow from a template
    result = client.submit_workflow_from_template(
        template_name="example-template",
        proposal_code="mg", proposal_number=36964, visit_number=1,
        parameters={"png": "True", "jpg": "False", "jpeg": "True", "tif": "True"}
    )
"""

import json
import urllib.error
import urllib.request
from typing import Any


class GraphQLError(Exception):
    """Raised when the GraphQL response contains errors."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        messages = "; ".join(e.get("message", str(e)) for e in errors)
        super().__init__(f"GraphQL error(s): {messages}")


class WorkflowsClient:
    def __init__(self, url: str, token: str | None = None, timeout: int = 30):
        """
        Args:
            url:     Full GraphQL endpoint URL, e.g. "https://api.example.com/graphql"
            token:   Optional Bearer token for Authorization header.
            timeout: Request timeout in seconds.
        """
        self.url = url
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Core transport
    # ------------------------------------------------------------------

    def _execute(self, query: str, variables: dict | None = None) -> dict:
        """Send a GraphQL request and return the 'data' dict."""
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(
            self.url, data=payload, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

        print(body)  # Debug: print full response body

        if errors := body.get("errors"):
            raise GraphQLError(errors)

        return body.get("data", {})

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_workflow_templates(
        self,
        limit: int = 5,
        science_group: str | None = "CRYSTALLOGRAPHY",
    ) -> list[dict]:
        """Return workflow template nodes, optionally filtered by science group."""
        query = """
        query WorkflowTemplates($limit: Int, $scienceGroup: ScienceGroup) {
            workflowTemplates(limit: $limit, filter: {scienceGroup: $scienceGroup}) {
                nodes {
                    name
                    maintainer
                    title
                }
            }
        }
        """
        variables: dict[str, Any] = {"limit": limit}
        if science_group is not None:
            variables["scienceGroup"] = science_group

        data = self._execute(query, variables)
        return data["workflowTemplates"]["nodes"]

    def get_workflows(
        self,
        proposal_code: str,
        proposal_number: int,
        visit_number: int,
        limit: int = 10,
        creator: str | None = None,
        template: str | None = None,
        succeeded: bool | None = None,
    ) -> list[dict]:
        """Return workflow nodes for a given visit, with optional filters."""
        query = """
        query Workflows(
            $proposalCode: String!
            $proposalNumber: Int!
            $visitNumber: Int!
            $limit: Int
            $creator: String
            $template: String
            $succeeded: Boolean
        ) {
            workflows(
                visit: {
                    proposalCode: $proposalCode
                    proposalNumber: $proposalNumber
                    number: $visitNumber
                }
                limit: $limit
                filter: {
                    creator: $creator
                    template: $template
                    workflowStatusFilter: {succeeded: $succeeded}
                }
            ) {
                nodes {
                    name
                    status { __typename }
                }
            }
        }
        """
        variables: dict[str, Any] = {
            "proposalCode": proposal_code,
            "proposalNumber": proposal_number,
            "visitNumber": visit_number,
            "limit": limit,
            "creator": creator,
            "template": template,
            "succeeded": succeeded,
        }
        data = self._execute(query, variables)
        return data["workflows"]["nodes"]

    def get_workflow(
        self,
        proposal_code: str,
        proposal_number: int,
        visit_number: int,
        name: str,
    ) -> dict:
        """Return details for a single named workflow."""
        query = """
        query Workflow(
            $proposalCode: String!
            $proposalNumber: Int!
            $visitNumber: Int!
            $name: String!
        ) {
            workflow(
                visit: {
                    proposalCode: $proposalCode
                    proposalNumber: $proposalNumber
                    number: $visitNumber
                }
                name: $name
            ) {
                name
                parameters
                templateRef
                creator { creatorId }
                status { __typename }
            }
        }
        """
        variables = {
            "proposalCode": proposal_code,
            "proposalNumber": proposal_number,
            "visitNumber": visit_number,
            "name": name,
        }
        data = self._execute(query, variables)
        return data["workflow"]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def submit_workflow_from_template(
        self,
        template_name: str,
        proposal_code: str,
        proposal_number: int,
        visit_number: int,
        parameters: dict[str, str] | None = None,
    ) -> dict:
        """
        Create a new workflow from an existing template.

        Args:
            template_name:   Name of the workflow template to use.
            proposal_code:   e.g. "mg"
            proposal_number: e.g. 36964
            visit_number:    e.g. 1
            parameters:      Key/value pairs forwarded to the template,
                             e.g. {"png": "True", "jpg": "False"}.

        Returns:
            Dict containing at minimum {"name": "<new-workflow-name>"}.
        """
        mutation = """
        mutation SubmitWorkflowFromTemplate(
            $name: String!
            $proposalCode: String!
            $proposalNumber: Int!
            $visitNumber: Int!
            $parameters: JSONObject
        ) {
            submitWorkflowTemplate(
                name: $name
                visit: {
                    proposalCode: $proposalCode
                    proposalNumber: $proposalNumber
                    number: $visitNumber
                }
                parameters: $parameters
            ) {
                name
            }
        }
        """
        variables = {
            "name": template_name,
            "proposalCode": proposal_code,
            "proposalNumber": proposal_number,
            "visitNumber": visit_number,
            "parameters": parameters or {},
        }
        data = self._execute(mutation, variables)
        return data["submitWorkflowTemplate"]


# ------------------------------------------------------------------
# Quick smoke-test (run directly: python graphql_client.py)
# ------------------------------------------------------------------
if __name__ == "__main__":
    from arrows.auth.auth_client import AuthClient

    client = AuthClient()
    print("Getting token")
    # client.list_reponse()
    TOKEN = client.get_auth_token()
    print("Token:", TOKEN)

    print("Token:", TOKEN)

    ENDPOINT = "https://workflows.diamond.ac.uk/graphql"

    client = WorkflowsClient(url=ENDPOINT, token=TOKEN)

    # print("=== Workflow Templates ===")
    templates = client.get_workflow_templates(limit=5, science_group="CRYSTALLOGRAPHY")
    # for t in templates:
    #     print(f"  {t['name']} — {t['title']} (maintainer: {t['maintainer']})")

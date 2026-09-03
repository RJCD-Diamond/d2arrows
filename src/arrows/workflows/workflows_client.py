"""
GraphQL client for workflow queries and mutations.

Usage:
    client = WorkflowClient(url="https://your-graphql-endpoint", token="your-token")

    # List workflow templates
    templates = client.get_workflow_templates(science_group="IMAGING", limit=5)

    # Get filtered workflows for a visit
    workflows = client.get_workflows(
        instrument_session="mg36964-1",
        creator="gmg29649", template="example-template", succeeded=True
    )

    # Get a specific workflow
    workflow = client.get_workflow(
        instrument_session="mg36964-1",
        name="conditional-steps-tswxm"
    )

    # Submit a workflow from a template
    result = client.submit_workflow_from_template(
        template_name="example-template",
        instrument_session="mg36964-1",
        parameters={"png": "True", "jpg": "False", "jpeg": "True", "tif": "True"}
    )
"""

from typing import Any

from arrows.core.graphql import BaseGraphqlClient
from arrows.utils import split_instrument_session

WORKFLOWS_ENDPOINT = "https://workflows.diamond.ac.uk/graphql"


class WorkflowsClient(BaseGraphqlClient):
    def __init__(
        self,
        instrument_session: str,
        science_group: str = "CRYSTALLOGRAPHY",
        url: str | None = None,
        timeout: int = 30,
    ):
        """
        Args:
            instrument_session eg: cm12345-1,
            science_group eg: "CRYSTALLOGRAPHY",
            timeout: Request timeout in seconds.
        """

        self.science_group = science_group.upper()

        self.url = url or WORKFLOWS_ENDPOINT
        self.timeout = timeout

        self.instrument_session = instrument_session

        self.proposal_code, self.proposal_number, self.visit_number = (
            split_instrument_session(instrument_session)
        )

        super().__init__(url=self.url, timeout=self.timeout)

    def set_instrument_session(self, instrument_session):

        self.instrument_session = instrument_session

        self.proposal_code, self.proposal_number, self.visit_number = (
            split_instrument_session(instrument_session)
        )

    def get_proposal_codes(self, instrument_session: str | None):
        if instrument_session is not None:
            proposal_code, proposal_number, visit_number = split_instrument_session(
                instrument_session
            )
        else:
            proposal_code, proposal_number, visit_number = (
                self.proposal_code,
                self.proposal_number,
                self.visit_number,
            )

        return proposal_code, proposal_number, visit_number

    def get_science_group(self, science_group: str | None) -> str:

        return science_group or self.science_group

    def get_workflow_templates(
        self,
        limit: int = 5,
        science_group: str | None = None,
    ) -> list[dict]:
        """Return workflow template nodes, optionally filtered by science group."""

        science_group = self.get_science_group(science_group)

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

        data = self.execute_query(query, variables)
        return data["workflowTemplates"]["nodes"]

    def get_workflows(
        self,
        instrument_session: str | None = None,
        succeeded: bool = True,
        limit: int = 10,
        creator: str | None = None,
        template: str | None = None,
    ) -> list[dict]:
        """Return workflow nodes for a given visit, with optional filters."""

        proposal_code, proposal_number, visit_number = self.get_proposal_codes(
            instrument_session
        )

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
        data = self.execute_query(query, variables)
        return data["workflows"]["nodes"]

    def get_workflow(
        self,
        name: str,
        instrument_session: str | None = None,
    ) -> dict:
        """Return details for a single named workflow."""

        proposal_code, proposal_number, visit_number = self.get_proposal_codes(
            instrument_session
        )

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
        data = self.execute_query(query, variables)
        return data["workflow"]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def submit_workflow_from_template(
        self,
        template_name: str,
        instrument_session: str | None = None,
        parameters: dict[str, Any] | None = None,
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

        proposal_code, proposal_number, visit_number = self.get_proposal_codes(
            instrument_session
        )

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

        # print(parameters)

        variables = {
            "name": template_name,
            "proposalCode": proposal_code,
            "proposalNumber": proposal_number,
            "visitNumber": visit_number,
            "parameters": parameters or {},
        }
        data = self.execute_query(mutation, variables)
        return data["submitWorkflowTemplate"]


# ------------------------------------------------------------------
# Quick smoke-test (run directly: python graphql_client.py)
# ------------------------------------------------------------------
if __name__ == "__main__":
    client = WorkflowsClient("cm44163-3", science_group="CRYSTALLOGRAPHY")

    # templates = client.get_workflow_templates()
    # pprint(templates)

    # print(client.get_proposal_codes("cm44163-3"))

    # workflows = client.get_workflows()

    data = client.submit_workflow_from_template(
        "i15-1-test-gaussian",
        instrument_session="cm44163-3",
        parameters={"centre": 5, "amplitude": 10},
    )

    print(data)

    # pprint(workflows)

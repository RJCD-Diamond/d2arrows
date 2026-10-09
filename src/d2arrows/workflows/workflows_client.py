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

import time
from typing import Any

from d2arrows.core.graphql import BaseGraphqlClient
from d2arrows.utils import split_instrument_session

WORKFLOWS_ENDPOINT = "https://workflows.diamond.ac.uk/graphql"


class WorkflowFailedError(Exception):
    """Raised when a waited-on workflow ends in a failed or errored state."""


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

    def get_visit_input(self, instrument_session: str | None) -> dict:
        """Build a VisitInput; triggers are namespaced per visit."""

        proposal_code, proposal_number, visit_number = self.get_proposal_codes(
            instrument_session
        )
        return {
            "proposalCode": proposal_code,
            "proposalNumber": proposal_number,
            "number": visit_number,
        }

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

    def create_trigger_for_visit(
        self, trigger_template: str, instrument_session: str | None = None
    ) -> dict:
        """Create a trigger from a trigger template for a specific visit."""

        query = """
        mutation createTrigger($templateRef: String!, $visit: VisitInput) {
        createTrigger(templateRef: $templateRef, visit: $visit) {
            name
        }
        }
        """

        variables = {
            "templateRef": trigger_template,
            "visit": self.get_visit_input(instrument_session),
        }
        data = self.execute_query(query, variables)
        return data["createTrigger"]

    def create_trigger(self, trigger_template: str) -> dict:
        """Create a trigger from a trigger template for a visit."""

        query = """
        mutation maketrigger($templateRef: String!) {
        createTrigger(templateRef: $templateRef) {
            name
        }
        }
        """
        data = self.execute_query(query, {"templateRef": trigger_template})
        return data["createTrigger"]

    def disable_trigger(self, name: str, instrument_session: str | None = None) -> dict:
        """Disable a trigger by name."""

        query = """
        mutation disableTrigger($name: String!, $visit: VisitInput) {
        disableTrigger(name: $name, visit: $visit) {
            name
        }
        }
        """
        variables = {"name": name, "visit": self.get_visit_input(instrument_session)}
        data = self.execute_query(query, variables)
        return data["disableTrigger"]

    def enable_trigger(self, name: str, instrument_session: str | None = None) -> dict:
        """enable a trigger by name."""

        query = """
        mutation enableTrigger($name: String!, $visit: VisitInput) {
        enableTrigger(name: $name, visit: $visit) {
            name
        }
        }
        """
        variables = {"name": name, "visit": self.get_visit_input(instrument_session)}
        data = self.execute_query(query, variables)
        return data["enableTrigger"]

    def delete_trigger(self, name: str, instrument_session: str | None = None) -> dict:
        """delete a trigger by name."""

        query = """
        mutation deleteTrigger($name: String!, $visit: VisitInput) {
        deleteTrigger(name: $name, visit: $visit) {
            name
        }
        }
        """
        variables = {"name": name, "visit": self.get_visit_input(instrument_session)}
        data = self.execute_query(query, variables)
        return data["deleteTrigger"]

    def get_triggers(self, limit: int = 10) -> list[dict]:
        """Return trigger nodes, including whether each is enabled."""

        query = """
        query Triggers($limit: Int) {
        triggers(limit: $limit) {
            nodes {
                name
                templateRef
                beamline
                enabled
            }
        }
        }
        """
        data = self.execute_query(query, {"limit": limit})
        return data["triggers"]["nodes"]

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
        wait_for_completion: bool = False,
        poll_interval: float = 1.0,
        wait_timeout: float | None = None,
    ) -> str:
        """
        Create a new workflow from an existing template.

        Args:
            template_name:   Name of the workflow template to use.
            proposal_code:   e.g. "mg"
            proposal_number: e.g. 36964
            visit_number:    e.g. 1
            parameters:      Key/value pairs forwarded to the template,
                             e.g. {"png": "True", "jpg": "False"}.
            wait_for_completion: If True, block until the workflow succeeds.
            poll_interval:   Seconds between status checks while waiting.
            wait_timeout:    Max seconds to wait, or None to wait indefinitely.

        Returns:
            The name of the new workflow.

        Raises:
            WorkflowFailedError: If waiting and the workflow fails or errors.
            TimeoutError: If waiting and wait_timeout is exceeded.
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
        workflow_name = data["submitWorkflowTemplate"]["name"]

        if wait_for_completion:
            self.wait_for_workflow(
                workflow_name,
                instrument_session=instrument_session,
                poll_interval=poll_interval,
                timeout=wait_timeout,
            )

        return workflow_name

    def get_workflow_status(
        self, name: str, instrument_session: str | None = None
    ) -> dict | None:
        """Return a workflow status, eg {"__typename": "WorkflowRunningStatus"}."""

        query = """
        query WorkflowStatus($visit: VisitInput!, $name: String!) {
            workflow(visit: $visit, name: $name) {
                status {
                    __typename
                    ... on WorkflowFailedStatus { message tasks { name message } }
                    ... on WorkflowErroredStatus { message tasks { name message } }
                }
            }
        }
        """
        variables = {"visit": self.get_visit_input(instrument_session), "name": name}
        data = self.execute_query(query, variables)
        return data["workflow"]["status"]

    def wait_for_workflow(
        self,
        name: str,
        instrument_session: str | None = None,
        poll_interval: float = 1.0,
        timeout: float | None = None,
    ) -> None:
        """Block until a workflow succeeds; raise if it fails, errors or times out."""

        start_time = time.monotonic()

        while True:
            status = self.get_workflow_status(name, instrument_session) or {}
            typename = status.get("__typename")

            if typename == "WorkflowSucceededStatus":
                return
            if typename in ("WorkflowFailedStatus", "WorkflowErroredStatus"):
                messages = [status.get("message")] + [
                    f"{task['name']}: {task['message']}"
                    for task in status.get("tasks", [])
                    if task.get("message")
                ]
                details = "; ".join(m for m in messages if m)
                raise WorkflowFailedError(
                    f"Workflow {name} ended with {typename}: {details}"
                )
            if timeout is not None and time.monotonic() - start_time > timeout:
                raise TimeoutError(
                    f"Workflow {name} did not complete within {timeout}s"
                )

            time.sleep(poll_interval)


def batch_process(
    instrument_session: str,
    filenumber_range: tuple[int, int],
    science_group: str = "CRYSTALLOGRAPHY",
) -> None:
    """Batch process a range of filenumbers using the workflows client."""

    client = WorkflowsClient("cm44163-4", science_group=science_group)

    for filenumber in range(*filenumber_range):
        print(filenumber)

        try:
            client.submit_workflow_from_template(
                template_name="i15-1-eiger-analysis",
                instrument_session=instrument_session,
                parameters={
                    "filenumber": filenumber,
                    "visitdir": f"/dls/i15-1/data/2026/{instrument_session}",
                },
                wait_for_completion=True,
                poll_interval=1.0,
            )
        except Exception as e:
            print(f"Workflow submission failed for filenumber {filenumber}: {e}")


def benchmark_workflows(
    workflows_template: str = "i15-1-test-gaussian",
    parameters: dict[str, Any] = {"centre": 5, "amplitude": 10},  # noqa
    instrument_session: str = "cm44163-3",
) -> list[float]:

    import time

    import numpy as np

    print("Benchmarking workflows...")

    def time_workflows():

        start_time = time.time()

        submitted_workflow_name = client.submit_workflow_from_template(
            workflows_template,
            instrument_session=instrument_session,
            parameters=parameters,
            wait_for_completion=True,
        )

        print(submitted_workflow_name)

        duration = time.time() - start_time
        return duration

    iterations = 20

    durations = []

    for iter in range(iterations):
        duration = time_workflows()
        durations.append(duration)
        print(iter, duration)

    print(
        f"mean {np.mean(durations):.2f} "
        f"stddev {np.std(durations):.2f} "
        f"min {np.amin(durations):.2f}"
    )

    return durations


if __name__ == "__main__":
    client = WorkflowsClient("cm44163-4", science_group="CRYSTALLOGRAPHY")

    # benchmark_workflows()

    # templates = client.get_workflow_templates()
    # print(templates)

    # print(client.get_proposal_codes("cm44163-3"))

    # trigger_name = client.create_trigger(
    #     trigger_template="i15-1-eiger-reduction-trigger",
    # )

    # print(client.get_triggers())

    # client.delete_trigger("i15-1-eiger-reduction-trigger-fnz8r")

    # client.disable_trigger("i15-1-eiger-reduction-trigger-fnz8r")

    # workflows = client.get_workflows()

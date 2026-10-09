"""
GraphQL client for instrument session queries.

Usage:
    client = SessionsClient()

    # All sessions on a beamline that you are authorised to see
    sessions = client.get_instrument_sessions(instrument="i15-1")

    # Only sessions currently running
    sessions = client.get_instrument_sessions(instrument="i15-1", state="IN_PROGRESS")

    # Sessions in any of several states
    sessions = client.get_instrument_sessions(
        instrument="i15-1", state=["IN_PROGRESS", "FUTURE"]
    )
"""

from typing import Any, Literal, get_args

from d2arrows.core.graphql import BaseGraphqlClient

GRAPH_ENDPOINT = "https://graph.diamond.ac.uk/graphql"

# The instrument_sessions subgraph rejects page sizes above this
MAX_PAGE_SIZE = 50

SessionState = Literal["FUTURE", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
SESSION_STATES: tuple[SessionState, ...] = get_args(SessionState)


class SessionsClient(BaseGraphqlClient):
    def __init__(self, url: str | None = None, timeout: int = 30):
        """
        Args:
            url:     GraphQL endpoint, defaults to the Diamond graph gateway.
            timeout: Request timeout in seconds.
        """

        super().__init__(url=url or GRAPH_ENDPOINT, timeout=timeout)

    def get_instrument_sessions(
        self,
        instrument: str | None = None,
        state: SessionState | list[SessionState] | None = None,
        limit: int | None = None,
    ) -> list[str]:
        """
        Return the instrument sessions you are authorised to see, newest first.

        Args:
            instrument: Beamline name eg "i15-1". Without this, every visible
                        session across the facility is fetched, which is slow.
            state:      One or a list of FUTURE, IN_PROGRESS, COMPLETED,
                        CANCELLED. None returns sessions in any state.
            limit:      Max number of sessions to return, or None for all.

        Returns:
            Session references eg ["nr47394-1", "cm44163-4"].
        """

        if state is None:
            sessions = self._fetch_sessions(instrument, None, limit)
        else:
            states: list[SessionState] = [state] if isinstance(state, str) else state
            for session_state in states:
                if session_state not in SESSION_STATES:
                    raise ValueError(f"state must be one of {SESSION_STATES}")

            # The API only filters on a single state, so query each one and
            # merge, keeping the newest-first order across all of them
            sessions = []
            for session_state in dict.fromkeys(states):
                sessions.extend(self._fetch_sessions(instrument, session_state, limit))
            sessions.sort(key=lambda session: session[0] or "", reverse=True)

        if limit is not None:
            sessions = sessions[:limit]

        return [reference for _, reference in sessions]

    def _fetch_sessions(
        self,
        instrument: str | None,
        state: SessionState | None,
        limit: int | None,
    ) -> list[tuple[str | None, str]]:
        """Page through sessions, returning (startTime, reference) pairs."""

        filter_by: dict[str, Any] = {}
        if state is not None:
            filter_by["state"] = {"eq": state}

        connection_args = """
            first: $first
            after: $after
            filterBy: $filterBy
            sortBy: [{field: startTime, orderBy: DESC}]
        """
        connection_fields = """
            edges { node { instrumentSessionReference startTime } }
            pageInfo { hasNextPage endCursor }
        """

        if instrument is not None:
            query = f"""
            query InstrumentSessions(
                $name: String!
                $first: Int
                $after: String
                $filterBy: InstrumentSessionFilterInput
            ) {{
                instrumentByName(name: $name) {{
                    instrumentSessions({connection_args}) {{ {connection_fields} }}
                }}
            }}
            """
        else:
            query = f"""
            query InstrumentSessions(
                $first: Int
                $after: String
                $filterBy: InstrumentSessionFilterInput
            ) {{
                instrumentSessions({connection_args}) {{ {connection_fields} }}
            }}
            """

        variables: dict[str, Any] = {"filterBy": filter_by}
        if instrument is not None:
            # Instrument names are stored upper case, eg "I15-1"
            variables["name"] = instrument.upper()

        sessions: list[tuple[str | None, str]] = []
        after = None

        while limit is None or len(sessions) < limit:
            page_size = MAX_PAGE_SIZE
            if limit is not None:
                page_size = min(page_size, limit - len(sessions))

            variables.update({"first": page_size, "after": after})
            data = self.execute_query(query, variables)

            if instrument is not None:
                if data["instrumentByName"] is None:
                    raise ValueError(f"Unknown instrument: {instrument!r}")
                connection = data["instrumentByName"]["instrumentSessions"]
            else:
                connection = data["instrumentSessions"]

            sessions.extend(
                (
                    edge["node"]["startTime"],
                    edge["node"]["instrumentSessionReference"].lower(),
                )
                for edge in connection["edges"]
            )

            if not connection["pageInfo"]["hasNextPage"]:
                break
            after = connection["pageInfo"]["endCursor"]

        return sessions


if __name__ == "__main__":
    client = SessionsClient()

    print(client.get_instrument_sessions(instrument="i15-1", state="IN_PROGRESS"))

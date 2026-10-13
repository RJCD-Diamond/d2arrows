import time
from pprint import pprint
from typing import Any

from tiled.client import from_uri
from tiled.client.composite import CompositeClient
from tiled.client.container import Container
from tiled.queries import Comparison, Eq

TILED_URL = "https://tiled.diamond.ac.uk"


TILED_STALE_TIME = 60 * 60 * 24  # 1 day in seconds

tiled_client = from_uri(uri=TILED_URL)


# results_container: Container = (
#     tiled_client.search(Eq("start.instrument", "i15-1"))
#     .search(Eq("start.instrument_session", instrument_session))
#     .search(Eq("stop.exit_status", "success"))
#     .search(Comparison("ge", "stop.time", oldest_valid_time))
#     .search(In("start.scan_type", list(AuxiliaryScanType)))
#     .search(KeyPresent("start.experiment_definition.data.time_per_pdf"))
# )


def sort_results_container(container: Container) -> list[tuple[str, dict]]:
    sorted_results = sorted(
        ((key, value) for key, value in container.items()),
        key=lambda item: item[1].metadata["start"]["time"],
        reverse=True,
    )
    return sorted_results


def container_to_dict(container: Container, read_data: bool = True) -> dict[str, Any]:
    """
    Recursively convert a tiled Container into a nested dict.

    Args:
        container: Container to convert, eg a run or one of its streams.
        read_data: If True, read each leaf node into memory, eg arrays become
                   numpy arrays. Large detector images make this slow, so set
                   False to keep the leaves as lazy tiled clients instead.

    Returns:
        Dict mirroring the container's structure, eg
        {"primary": {"fastcs_eiger": array(...), ...}, "baseline": {...}}.
    """

    container_dict: dict[str, Any] = {}

    for key, node in container.items():
        if read_data and isinstance(node, CompositeClient):
            # Iterating a composite (eg a stream) re-lists it for every child,
            # so read the whole thing in one go: ~1s instead of ~10s per stream
            try:
                dataset = node.read()
                container_dict[key] = {
                    name: dataset[name].values for name in dataset.data_vars
                }
            except Exception:
                pass
        elif isinstance(node, Container):
            try:
                container_dict[key] = container_to_dict(node, read_data=read_data)
            except Exception:
                pass
        else:
            container_dict[key] = node.read() if read_data else node

    return container_dict


class TiledClient:
    def __init__(self, beamline: str, url: str = TILED_URL):

        self.beamline = beamline
        self.client = from_uri(uri=url)
        self.oldest_valid_time = time.time() - TILED_STALE_TIME

    def get_last_results_container(
        self, instrument_session: str, oldest_time: str | None = None
    ) -> Container:

        oldest_valid_time = oldest_time or self.oldest_valid_time

        results_container = (
            self.client.search(Eq("start.instrument", self.beamline))
            .search(Eq("start.instrument_session", instrument_session))
            .search(Eq("stop.exit_status", "success"))
            .search(Comparison("ge", "stop.time", oldest_valid_time))
        )

        return results_container

    def get_scan_file_container(
        self, instrument_session: str, scan_number: int, as_dict: bool = True
    ) -> Container | dict:

        results_container = (
            self.client.search(Eq("start.instrument", self.beamline))
            .search(Eq("start.instrument_session", instrument_session))
            .search(Eq("start.scan_id", scan_number))
        )

        if as_dict:
            results_dict = container_to_dict(results_container)
            return results_dict
        else:
            return results_container


if __name__ == "__main__":
    tiled_client = TiledClient(beamline="i15-1")

    # sorted_results = sort_results_container(
    #     tiled_client.get_last_results_container(instrument_session="cm44163-4")
    # )

    scan_meatadata_container = tiled_client.get_scan_file_container(
        instrument_session="cm44163-4", scan_number=100262, as_dict=True
    )

    pprint(scan_meatadata_container)

    scan_meatadata_container = tiled_client.get_scan_file_container(
        instrument_session="cm44163-4", scan_number=100260, as_dict=True
    )

    pprint(scan_meatadata_container)

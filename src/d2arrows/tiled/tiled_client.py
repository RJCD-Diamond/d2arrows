import time
from pprint import pprint
from typing import Any
from urllib.parse import urlparse

import tiled.client.utils
from tiled.client import from_uri
from tiled.client.composite import CompositeClient
from tiled.client.container import Container
from tiled.queries import Comparison, Eq

TILED_URL = "https://tiled.diamond.ac.uk"


tiled.client.utils.TILED_RETRY_ATTEMPTS = 2


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


def get_file_path(item: dict) -> str | None:
    """
    Return the file a tiled node's data is stored in, eg a detector HDF5 file.

    Returns None for data held in tiled's own database, or when the client was
    created without include_data_sources=True.
    """

    for data_source in item["attributes"].get("data_sources") or []:
        if data_source["management"] != "external":
            continue
        for asset in data_source["assets"]:
            data_uri = urlparse(asset["data_uri"])
            if data_uri.scheme == "file":
                return data_uri.path

    return None


def composite_to_dict(composite: CompositeClient) -> dict[str, Any]:
    """Read a composite (eg a stream), with file paths for file-backed data."""

    composite_dict: dict[str, Any] = {}
    variables: list[str] = []

    # One request lists every child, along with where its data is stored
    for name, item in composite.get_contents().items():
        if file_path := get_file_path(item):
            composite_dict[name] = file_path
        elif item["attributes"]["structure_family"] == "table":
            # Tables are flattened, so each column is its own variable
            variables.extend(item["attributes"]["structure"]["columns"])
        else:
            variables.append(name)

    if not variables:
        return composite_dict

    try:
        dataset = composite.read(variables=variables)
        composite_dict.update({name: dataset[name].values for name in variables})
    except Exception:
        # Fall back to reading each variable, so unreadable ones are None
        for name in variables:
            try:
                composite_dict[name] = composite[name].read()
            except Exception:
                composite_dict[name] = None

    return composite_dict


def container_to_dict(container: Container, read_data: bool = True) -> dict[str, Any]:
    """
    Recursively convert a tiled Container into a nested dict.

    Args:
        container: Container to convert, eg a run or one of its streams.
        read_data: If True, read each leaf node into memory, eg arrays become
                   numpy arrays, except data stored in files, eg detector
                   images, which is returned as the file path. Set False to
                   keep the leaves as lazy tiled clients instead.

    Returns:
        Dict mirroring the container's structure, eg
        {"primary": {"fastcs_eiger": "/dls/.../i15-1-100225-fastcs_eiger_000001.h5",
                     "i0": "/dls/.../i15-1-100225-i0.h5"},
         "baseline": {"seq_num": array([1, 2]), ...}}.
    """

    container_dict: dict[str, Any] = {}

    for key, node in container.items():
        if read_data and isinstance(node, CompositeClient):
            # Iterating a composite (eg a stream) re-lists it for every child,
            # so read the whole thing in one go: ~1s instead of ~10s per stream
            container_dict[key] = composite_to_dict(node)
        elif isinstance(node, Container):
            try:
                container_dict[key] = container_to_dict(node, read_data=read_data)
            except Exception:
                container_dict[key] = {}
        elif read_data and (file_path := get_file_path(node.item)):
            container_dict[key] = file_path
        elif read_data:
            try:
                container_dict[key] = node.read()
            except Exception:
                container_dict[key] = None
        else:
            container_dict[key] = node

    return container_dict


class TiledClient:
    def __init__(self, beamline: str, url: str = TILED_URL):

        self.beamline = beamline
        # Data sources say where each node's data is stored, eg a file path
        self.client = from_uri(uri=url, include_data_sources=True)
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

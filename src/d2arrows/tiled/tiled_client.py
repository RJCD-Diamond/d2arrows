import json
import time
from copy import deepcopy
from typing import Any, cast
from urllib.parse import urlparse

import tiled.client.utils
from tiled.client import from_uri
from tiled.client.composite import CompositeClient
from tiled.client.container import Container
from tiled.queries import Comparison, Eq

TILED_URL = "https://tiled.diamond.ac.uk"


tiled.client.utils.TILED_RETRY_ATTEMPTS = 1


TILED_STALE_TIME = 60 * 60 * 24  # 1 day in seconds

tiled_client = from_uri(uri=TILED_URL)


def get_run_container_from_uid(uid: str):

    return from_uri(f"{TILED_URL}/api/v1/metadata/{uid}")


def get_total_exposure_time(run: Container) -> float:
    """
    Return a run's total detector exposure time in seconds.

    This is the number of frames collected times exposure_time_per_frame
    from the start document. Frames are counted from what was collected,
    as collection_specification has changed format between scans:
    one event per frame in the "data" stream, or for scans without one
    (eg static_collection, centre_sample) one i0 reading per frame.
    """

    start = cast(dict[str, Any], run.metadata["start"])
    stop = cast(dict[str, Any], run.metadata["stop"])

    frames = stop.get("num_events", {}).get("data")
    if frames is None:
        data_keys = cast(dict[str, Any], run["primary"].metadata["data_keys"])
        frames = data_keys["fastcs_eiger"]["shape"][0]

    return frames * start["exposure_time_per_frame"]


def sort_results_container(container: Container) -> list[tuple[str, Container]]:
    sorted_results = sorted(
        ((key, value) for key, value in container.items()),
        key=lambda item: item[1].metadata["start"]["time"],
        reverse=True,
    )
    return sorted_results


def get_external_source(item: dict) -> tuple[str, str | None] | None:
    """
    Return (file path, HDF5 dataset) for a tiled node stored in a file, eg
    ("/dls/.../i15-1-100225-i0.h5", "/entry/data/data").

    Returns None for data held in tiled's own database, or when the client was
    created without include_data_sources=True.
    """

    for data_source in item["attributes"].get("data_sources") or []:
        if data_source["management"] != "external":
            continue
        for asset in data_source["assets"]:
            data_uri = urlparse(asset["data_uri"])
            if data_uri.scheme == "file":
                dataset = (data_source.get("parameters") or {}).get("dataset")
                return data_uri.path, dataset

    return None


def get_file_path(item: dict) -> str | None:
    """
    Return the file a tiled node's data is stored in, eg a detector HDF5 file.

    Returns None for data held in tiled's own database, or when the client was
    created without include_data_sources=True.
    """

    external_source = get_external_source(item)
    return external_source[0] if external_source else None


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
         "baseline": {"seq_num": array([1, 2]), ...},
         "metadata": {
             "start": {"scan_id": 100225, "sample_info": {...}, ...},
             "stop": {"exit_status": "success", "num_events": {...}, ...}}}

        A run's start and stop documents are under "metadata", as they are
        in container.metadata.
    """

    container_dict: dict[str, Any] = {}

    # A run's start and stop documents: sample, experiment definition,
    # exit status, etc.
    metadata = {
        document: deepcopy(container.metadata[document])
        for document in ("start", "stop")
        if document in container.metadata
    }
    if metadata:
        container_dict["metadata"] = metadata

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


def get_start_stop(run: Container):

    return run.metadata["start"], run.metadata["stop"]


class TiledClient:
    def __init__(
        self, beamline: str, url: str = TILED_URL, include_data_sources: bool = True
    ):

        self.beamline = beamline
        # Data sources say where each node's data is stored, eg a file path
        self.client = from_uri(uri=url, include_data_sources=include_data_sources)
        self.oldest_valid_time = time.time() - TILED_STALE_TIME

    def get_last_results_container(
        self,
        instrument_session: str,
        oldest_time: float | None = None,
        exit_status: str = "success",
    ) -> Container:

        oldest_valid_time = oldest_time or self.oldest_valid_time

        results_container = (
            self.client.search(Eq("start.instrument", self.beamline))
            .search(Eq("start.instrument_session", instrument_session))
            .search(Eq("stop.exit_status", exit_status))
            .search(Comparison("ge", "stop.time", oldest_valid_time))
        )

        return results_container

    def get_run_container(
        self, instrument_session: str, scan_number: int
    ) -> tuple[str, Container]:
        """
        Find a scan's run in tiled.

        Returns:
            (uid, run): the run's uuid, and the run as a tiled Container.

        Raises:
            ValueError: If no run, or more than one, matches the scan number.
        """

        results_container = (
            self.client.search(Eq("start.instrument", self.beamline))
            .search(Eq("start.instrument_session", instrument_session))
            .search(Eq("start.scan_id", scan_number))
        )

        if len(results_container) != 1:
            raise ValueError(
                f"Expected 1 run for scan {scan_number} in {instrument_session}, "
                f"found {len(results_container)}"
            )

        uid = next(iter(results_container))
        return uid, results_container[uid]

    def get_run(
        self, instrument_session: str, scan_number: int
    ) -> tuple[str, dict[str, dict | Any]]:
        """
        Find a scan's run in tiled and convert it to a dict.

        Returns:
            (uid, run): the run's uuid, and the run as a dict from
            container_to_dict, with its start and stop documents under
            "metadata", eg run["metadata"]["start"].

        Raises:
            ValueError: If no run, or more than one, matches the scan number.
        """

        uid, run_container = self.get_run_container(instrument_session, scan_number)
        return uid, container_to_dict(run_container)


class EigerTileDataLoader:
    def __init__(
        self,
        uid: str | None = None,
        scan_number: int | None = None,
        beamline: str = "i15-1",
    ):

        if (uid and scan_number is None) or (uid and scan_number is not None):
            raise ValueError("Either uid OR filenumber should be given")

        tiled_client = TiledClient(beamline=beamline)

        if scan_number is not None:
            uid, run = tiled_client.get_run_container(
                instrument_session="cm44163-4", scan_number=scan_number
            )


if __name__ == "__main__":
    import json

    tiled_client = TiledClient(beamline="i15-1")

    # scan_uid, scan_meatadata_container = tiled_client.get_run_container(
    #     instrument_session="cm44163-4", scan_number=100262
    # )

    # # scan_uid, scan_meatadata_container = tiled_client.get_run(
    # #     instrument_session="cm44163-4", scan_number=100260
    # # )
    # pprint(scan_meatadata_container)

    # # Paths only reach nodes (streams, arrays); scan_id is metadata on the run
    # scan_client = from_uri(
    #     f"{TILED_URL}/api/v1/metadata/{scan_uid}", include_data_sources=True
    # )

    # print(scan_client.metadata["start"]["scan_id"])
    # print(scan_client.metadata["stop"])
    # print(scan_client.metadata["start"])

    # print(scan_client["baseline"])
    # print(scan_client["primary"])
    # print(scan_client["data"])

    # ------------------------------------------------------------------
    # 1. Get a scan as a dict: data values, detector file paths and the
    #    run's start metadata
    # ------------------------------------------------------------------
    uid, run = tiled_client.get_run_container(
        instrument_session="cm44163-4", scan_number=100262
    )

    print(get_total_exposure_time(run))

    # list(run), run["primary"], items() #The streams: baseline, primary, data.
    # run.item["id"] / run.path_parts # The run's ID, and its path from the top of tiled
    # run.uri #	Its full URL, which you can pass to from_uri later or share
    # run.specs	# [Spec('BlueskyRun', version='3.0')], which marks it as a Bluesky run
    # run.access_blob #	{'tags': ['27566658']}: who can access it (the proposal's tag)
    # run.formats #What export supports for the whole run: json, and h5
    # run.refresh()	#Re-fetches it, e.g. for a scan that's still running
    # run.metadata_revisions #Edits made to the metadata after  scan (0 for these runs)
    # run.parent	The container above it

    uid, run = tiled_client.get_run(instrument_session="cm44163-4", scan_number=100262)
    print("uid:", uid)
    print("streams:", list(run))  # ['baseline', 'primary', 'data']

    print(run["metadata"].keys())
    print(run["baseline"].keys())
    print(run["primary"].keys())
    print(run["data"].keys())

    run_start = cast(dict[str, Any], run["metadata"]["start"])
    scan_file = run_start["scan_id"]

    # tiled's run.export can't write HDF5 for these runs, so write it locally
    # run.export(
    #     filepath=f"/workspaces/outputs/i15-1/{scan_file}_test.h5",
    # )

    collection_spec: dict = json.loads(run_start["collection_specification"])[0]

    print(len(collection_spec["collection_specification"]))

    # run.export(
    #     filepath=f"/workspaces/outputs/i15-1/{scan_file}_test.json",
    # )

    # results = run.create_container(key=f"{uid}-result")
    # results.write_array([1, 2, 3], key="test", metadata={"test": "12"})

    quit()

    # ------------------------------------------------------------------
    # 2. Start metadata: sample, experiment and scan settings
    # ------------------------------------------------------------------
    start = run["metadata"]["start"]
    print("sample:", start["sample_info"]["name"], start["sample_info"]["data"])
    print("temperatures:", start["variables"]["temperatures_celsius"])
    print("beam energy:", start["experiment_definition"]["data"]["beam_energy"])

    # Some fields are stored as JSON strings
    calibration = json.loads(start["geometry_calibration"])
    print("detector:", calibration["detector"])

    # ------------------------------------------------------------------
    # 3. Data values: the data stream is not stored in time order
    # ------------------------------------------------------------------
    data = run["data"]
    order = data["time"].argsort()
    tth = data["tth"][order]
    temperature = data["blower-temperature"][order]
    print("first readings:", list(zip(temperature[:3], tth[:3])))

    # ------------------------------------------------------------------
    # 4. Detector data is returned as the file it is stored in
    # ------------------------------------------------------------------
    for name, file_path in run["primary"].items():
        print(f"{name}: {file_path}")

    # ------------------------------------------------------------------
    # 5. Work with the tiled Container directly instead of a dict
    # ------------------------------------------------------------------
    uid, run_container = tiled_client.get_run_container(
        instrument_session="cm44163-4", scan_number=100225
    )
    print("specs:", run_container.specs)  # [Spec('BlueskyRun', ...)]
    print("access tags:", run_container.access_blob["tags"])
    # tiled types metadata as any JSON value, so cast to index into it
    stop = cast(dict[str, Any], run_container.metadata["stop"])
    print("exit status:", stop["exit_status"])

    # Paths need the real location: values stored in tiled are in "internal"
    print("tth via path:", run_container["data/internal/tth"].read()[:3])

    # Units and EPICS PVs for each value are in the stream metadata
    tth_key = run_container["data"].metadata["data_keys"]["tth"]
    print("tth units:", tth_key["units"], "from", tth_key["source"])

    # ------------------------------------------------------------------
    # 6. Open a run directly from its uid
    # ------------------------------------------------------------------
    run_from_uid = from_uri(f"{TILED_URL}/api/v1/metadata/{uid}")
    run_start = cast(dict[str, Any], run_from_uid.metadata["start"])
    print("scan_id from uid:", run_start["scan_id"])

    # ------------------------------------------------------------------
    # 7. Recent successful runs for a session, newest first
    # ------------------------------------------------------------------
    recent = tiled_client.get_last_results_container(
        instrument_session="cm44163-4", oldest_time=time.time() - 60 * 60 * 24 * 7
    )
    for run_uid, recent_run in sort_results_container(recent)[:5]:
        recent_start = cast(dict[str, Any], recent_run.metadata["start"])
        print(run_uid, recent_start["scan_id"])

    # ------------------------------------------------------------------
    # 8. Save to disk with tiled's export. The format comes from the file
    #    extension, or pass format="..."; node.formats lists what's allowed
    # ------------------------------------------------------------------
    scan_file = run_start["scan_file"]  # eg "i15-1-100225"

    # The run's metadata (start and stop) and structure, but no data values
    run_container.export(f"{scan_file}.json")

    # A stream's stored values are one table: csv, parquet, xlsx, arrow, ...
    data_table = run_container["data"].base["internal"]
    data_table.export(f"{scan_file}-data.csv")
    data_table.export(f"{scan_file}-data.parquet")
    run_container["baseline"].base["internal"].export(f"{scan_file}-baseline.xlsx")

    # A single array: csv, json, tiff, png, ..., optionally only a slice
    run_container["data"]["tth"].export(f"{scan_file}-tth.csv")
    run_container["data"]["tth"].export(
        f"{scan_file}-tth-first10.csv", slice=(slice(0, 10),)
    )

    # Not working on this server:
    # - HDF5 of a run or stream: tiled can't fit the nested metadata in HDF5
    # - primary (detector) arrays, in any format, and raw_export() of their
    #   files: the server can't read files on /dls. raw_export() only logs
    #   the error and writes nothing, so check the output exists

    # ------------------------------------------------------------------
    # 9. Writing to tiled (not run: needs a logged in client with write
    #    access to `parent`. Never write into the beamline's raw data)
    # ------------------------------------------------------------------
    # parent = ...  # a container the tiled admins have made writable for you
    # results = parent.create_container(
    #     key=f"{uid}-reduced",
    #     metadata={"source_run": uid, "scan_id": start["scan_id"]},
    #     access_tags=list(run_container.access_blob["tags"]),
    # )
    # results.write_array(tth, key="tth", metadata={"units": "deg"})

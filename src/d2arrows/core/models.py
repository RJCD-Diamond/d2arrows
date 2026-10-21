from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from event_model.basemodels import (
    Event,
    EventDescriptor,
    RunStart,
    RunStop,
    StreamDatum,
    StreamResource,
)
from pydantic import (
    BaseModel,
    Field,
)

############# blueapi events


class WorkerState(StrEnum):
    """
    The state of the Worker.
    """

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    HALTING = "HALTING"
    STOPPING = "STOPPING"
    ABORTING = "ABORTING"
    SUSPENDING = "SUSPENDING"
    PANICKED = "PANICKED"
    UNKNOWN = "UNKNOWN"


class WorkerEvent(BaseModel):
    """
    Event describing the state of the worker and any tasks it's running.
    Includes error and warning information.
    """

    state: WorkerState
    task_status: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


#### bluesky event_models


class RunStartDoc(RunStart):
    instrument: str
    instrument_session: str
    scan_file: str
    plan_name: str


# Validate against 'start' job messages
class StartMessage(BaseModel):
    name: Literal["start"]
    doc: RunStartDoc
    task_id: str


class RunStopDoc(RunStop):
    # Incase anything more is added to BlueAPI
    pass


# Validate against 'stop' job messages
class StopMessage(BaseModel):
    name: Literal["stop"]
    doc: RunStopDoc
    task_id: str


# Validate against 'descriptor' job messages
class DescriptorMessage(BaseModel):
    name: Literal["descriptor"]
    doc: EventDescriptor
    task_id: str


# Validate against 'event' job messages
class EventMessage(BaseModel):
    name: Literal["event"]
    doc: Event
    task_id: str


# Validate against 'stream_resource' job messages
class StreamResourceMessage(BaseModel):
    name: Literal["stream_resource"]
    doc: StreamResource
    task_id: str


# Validate against 'stream_datum' job messages
class StreamDatumMessage(BaseModel):
    name: Literal["stream_datum"]
    doc: StreamDatum
    task_id: str


JobMessage: TypeAlias = Annotated[
    StartMessage
    | DescriptorMessage
    | EventMessage
    | StreamResourceMessage
    | StreamDatumMessage
    | StopMessage,
    Field(discriminator="name"),
]

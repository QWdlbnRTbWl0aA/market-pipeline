"""Provider contracts. Provider text and briefs are data, never executable instructions."""
from dataclasses import dataclass
from dataclasses import field
from typing import Protocol


@dataclass(frozen=True)
class Asset:
    content: bytes
    media_type: str
    label: str
    metadata: dict = field(default_factory=dict)


class Generator(Protocol):
    def generate(self, request: dict) -> list[Asset]: ...


class Broker(Protocol):
    def publish(self, message: dict) -> dict: ...


class Listing(Protocol):
    def request_listing(self, approved: dict) -> dict: ...

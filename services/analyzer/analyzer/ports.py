"""Source and model contracts. No provider-specific imports belong here."""
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class IntakeBatch:
    records: list[dict[str, Any]]
    metadata: dict[str, Any]
    provenance: dict[str, Any]


@dataclass
class ModelRequest:
    system: str
    prompt: str
    schema: dict[str, Any]
    images: tuple[str, ...] = ()  # Base64 saved local image bytes; never URLs.


@dataclass
class ModelResponse:
    text: str
    metadata: dict[str, Any]
    raw: dict[str, Any]


class Intake(Protocol):
    def read(self) -> IntakeBatch: ...


class LanguageModel(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...

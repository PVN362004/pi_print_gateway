from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    original_filename: str
    stored_path: str
    extension: str
    selected_format: str
    printer: str
    title: str = "Print job"
    copies: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    adapter_response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def update(self, **values: Any) -> None:
        for key, value in values.items():
            setattr(self, key, value)
        self.updated_at = utc_now()

    def public_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

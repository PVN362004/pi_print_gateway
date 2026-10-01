from abc import ABC, abstractmethod
import json
import subprocess
from pathlib import Path
from typing import Any

import requests


class Adapter(ABC):
    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def submit(self, file_path: Path, job: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def cancel(self, job_id: str) -> bool:
        return False


class CupsAdapter(Adapter):
    def submit(self, file_path: Path, job: dict[str, Any]) -> dict[str, Any]:
        printer_name = self.config["printer_name"]
        command = [
            self.config.get("lp_command", "lp"),
            "-d", printer_name,
            "-n", str(job.get("copies", 1)),
            "-t", str(job.get("title") or "Print job")[:127],
        ]
        if self.config.get("raw") or job.get("selected_format") == "zpl":
            command.extend(["-o", "raw"])
        for key, value in self.config.get("options", {}).items():
            command.extend(["-o", f"{key}={value}"])
        command.append(str(file_path))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return {
            "status": "submitted",
            "cups_response": result.stdout.strip(),
            "command": command[:-1] + [file_path.name],
        }

    def cancel(self, job_id: str) -> bool:
        return subprocess.run(["cancel", job_id], check=False).returncode == 0


class OctoprintAdapter(Adapter):
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.config["api_key"]}

    def submit(self, file_path: Path, job: dict[str, Any]) -> dict[str, Any]:
        url = self.config["url"].rstrip("/") + "/api/files/local"
        with file_path.open("rb") as stream:
            response = requests.post(
                url,
                headers=self._headers(),
                files={"file": (job["original_filename"], stream, "application/octet-stream")},
                data={"print": str(self.config.get("auto_start", False)).lower()},
                timeout=120,
            )
        response.raise_for_status()
        return response.json() if response.content else {"status": "submitted"}

    def cancel(self, job_id: str) -> bool:
        url = self.config["url"].rstrip("/") + "/api/job"
        response = requests.post(
            url, headers=self._headers(), json={"command": "cancel"}, timeout=15
        )
        return response.ok


class MqttAdapter(Adapter):
    def submit(self, file_path: Path, job: dict[str, Any]) -> dict[str, Any]:
        import paho.mqtt.publish as publish

        payload = {
            "job_id": job["id"],
            "filename": job["original_filename"],
            "path": str(file_path),
            "metadata": job.get("metadata", {}),
        }
        publish.single(
            self.config["topic"],
            payload=json.dumps(payload),
            hostname=self.config.get("host", "127.0.0.1"),
            port=int(self.config.get("port", 1883)),
            qos=int(self.config.get("qos", 0)),
        )
        return {"status": "published", "topic": self.config["topic"]}


ADAPTERS = {
    "cups": CupsAdapter,
    "octoprint": OctoprintAdapter,
    "mqtt": MqttAdapter,
}


def create_adapter(config: dict[str, Any]) -> Adapter:
    adapter_type = config.get("type")
    if adapter_type not in ADAPTERS:
        raise ValueError(f"Unsupported adapter type: {adapter_type}")
    return ADAPTERS[adapter_type](config)

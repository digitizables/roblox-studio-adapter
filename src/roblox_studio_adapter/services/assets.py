"""Search, insert, and generate content. Long jobs are started async and polled."""

from __future__ import annotations

import time
from typing import Any

from roblox_studio_adapter.errors import EditError, TimeoutError
from roblox_studio_adapter.parsers import extract_json, parse_job
from roblox_studio_adapter.session import Session

_ASYNC_TOOLS = {"generate_mesh", "generate_material", "generate_procedural_model"}


class AssetService:
    def __init__(self, session: Session, sleep=time.sleep) -> None:
        self.session = session
        self.sleep = sleep

    def search(self, query: str = "", **filters: Any) -> Any:
        arguments = {"query": query, **filters}
        result = self.session.call("search_asset", arguments)
        return extract_json(result.text) if extract_json(result.text) is not None else result.text

    def insert(self, asset_id: str, *, name: str | None = None, asset_type: str | None = None, parent: str | None = None) -> str:
        result = self.session.call(
            "insert_asset",
            {
                "assetId": str(asset_id),
                "assetName": name,
                "assetType": asset_type,
                "parentPath": parent,
            },
        )
        return result.text

    def store_image(self, file_path: str) -> str:
        result = self.session.call("store_image", {"filePath": file_path})
        return result.text

    def generate_material(
        self,
        *,
        material_id: str,
        description: str,
        base_material: str = "Plastic",
        pattern: str = "Regular",
        wait: bool = True,
        timeout: float = 300,
    ) -> Any:
        return self._generate(
            "generate_material",
            {
                "materialId": material_id,
                "materialDescription": description,
                "baseMaterial": base_material,
                "materialPattern": pattern,
            },
            wait=wait,
            timeout=timeout,
        )

    def generate_procedural_model(self, prompt: str, *, image_uri: str | None = None, wait: bool = False, timeout: float = 600, **kwargs: Any) -> Any:
        """Start a procedural model. The tool's own guidance is to run it async.

        Pass ``wait=True`` only when the next step needs the inserted model.
        """
        return self._generate(
            "generate_procedural_model",
            {"prompt": prompt, "attachedImageUri": image_uri, **kwargs},
            wait=wait,
            timeout=timeout,
        )

    def generate_mesh(self, prompt: str, *, wait: bool = False, timeout: float = 600, **kwargs: Any) -> Any:
        return self._generate("generate_mesh", {"textPrompt": prompt, **kwargs}, wait=wait, timeout=timeout)

    def wait_job(self, job_id: str, *, timeout: float = 600) -> dict:
        """Poll wait_job_finished until the job ends or ``timeout`` seconds pass.

        Each call is capped near 45 seconds for external clients, so this loops.
        """
        deadline = time.monotonic() + timeout
        last = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Job {job_id} was still running after {timeout:.0f}s. Last status: {last}")
            slice_timeout = min(60, max(5, remaining))
            result = self.session.call("wait_job_finished", {"jobId": job_id, "timeout": min(45, remaining)}, timeout=slice_timeout)
            status = parse_job(result.text)
            last = status.status
            if status.status in {"Completed", "Failed", "Cancelled"}:
                return {"status": status.status, "job_id": job_id, "text": result.text}
            self.sleep(1.0)

    def _generate(self, tool: str, arguments: dict, *, wait: bool, timeout: float) -> Any:
        if tool in _ASYNC_TOOLS:
            arguments = {**arguments, "async": True}
        result = self.session.call(tool, arguments, timeout=90 if tool in _ASYNC_TOOLS else timeout)
        if not wait or tool not in _ASYNC_TOOLS:
            return extract_json(result.text) if extract_json(result.text) is not None else result.text
        payload = extract_json(result.text)
        job_id = None
        if isinstance(payload, dict):
            job_id = payload.get("jobId") or payload.get("job_id")
        if not job_id:
            found = parse_job(result.text)
            job_id = found.job_id
        if not job_id:
            raise EditError(f"{tool} was started async but the result had no jobId:\n{result.text[:500]}")
        return self.wait_job(str(job_id), timeout=timeout)

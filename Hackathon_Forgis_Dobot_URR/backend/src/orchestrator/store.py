"""File-based persistence for orchestrator FlowRun records."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .schemas import FlowRunRecord

logger = logging.getLogger(__name__)


class FlowRunStore:
    """Persist and query run records with retention pruning."""

    def __init__(self, runs_dir: str, retention: int = 200):
        self._runs_dir = Path(runs_dir)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._retention = retention

    def _run_path(self, flow_id: str) -> Path:
        safe_id = "".join(c for c in flow_id if c.isalnum() or c in "-_")
        return self._runs_dir / f"{safe_id}.json"

    def save(self, record: FlowRunRecord) -> None:
        path = self._run_path(record.flow_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.model_dump(), f, indent=2)
        self._prune()

    def get(self, flow_id: str) -> Optional[FlowRunRecord]:
        path = self._run_path(flow_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return FlowRunRecord.model_validate(data)
        except Exception as exc:
            logger.error("Failed to load run %s: %s", flow_id, exc)
            return None

    def list(self, limit: int = 20, offset: int = 0) -> list[FlowRunRecord]:
        runs: list[FlowRunRecord] = []
        for path in sorted(self._runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                runs.append(FlowRunRecord.model_validate(data))
            except Exception as exc:
                logger.warning("Skipping invalid run file %s: %s", path, exc)
        return runs[offset: offset + limit]

    def _prune(self) -> None:
        paths = sorted(self._runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(paths) <= self._retention:
            return
        for path in paths[self._retention:]:
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Failed to prune run file %s: %s", path, exc)

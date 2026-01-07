from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional
import logging
import pathlib

TASK_LOGGER = logging.getLogger("thoth.tasks")


@dataclass
class Task:
    name: str
    source: str
    channel: Optional[str]
    reason: str
    action: Callable[[], dict]

    @property
    def label(self) -> str:
        if self.channel:
            return f"{self.source}:{self.channel}"
        return self.source


class TaskQueue:
    def __init__(self, logger: logging.Logger = TASK_LOGGER) -> None:
        self._tasks: List[Task] = []
        self._logger = logger

    @property
    def tasks(self) -> List[Task]:
        return list(self._tasks)

    def add(self, task: Task) -> None:
        self._tasks.append(task)
        self._logger.info(
            "Task queued name=%s label=%s reason=%s",
            task.name,
            task.label,
            task.reason,
        )

    def run(self) -> None:
        for index, task in enumerate(self._tasks):
            next_task = self._tasks[index + 1] if index + 1 < len(self._tasks) else None
            self._logger.info(
                "Task status current=%s next=%s",
                f"{task.name}:{task.label}",
                f"{next_task.name}:{next_task.label}" if next_task else "none",
            )
            self._logger.info("Task start name=%s label=%s", task.name, task.label)
            try:
                result = task.action() or {}
                status = result.get("status", "ok")
                details = result.get("details") or ""
                self._logger.info(
                    "Task result name=%s label=%s status=%s details=%s",
                    task.name,
                    task.label,
                    status,
                    details,
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.exception(
                    "Task result name=%s label=%s status=error error=%s",
                    task.name,
                    task.label,
                    exc,
                )


def configure_task_logger(log_dir: pathlib.Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tasks.log"
    for handler in TASK_LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_path):
            return
    handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    TASK_LOGGER.addHandler(handler)
    TASK_LOGGER.setLevel(logging.INFO)
    TASK_LOGGER.propagate = True

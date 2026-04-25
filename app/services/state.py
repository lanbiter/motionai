import ast
from abc import ABC, abstractmethod

from loguru import logger

from app.config import config
from app.models import const
from app.services import video_archive_db


def _normalize_progress(progress: int | None, default: int = 0) -> int:
    if progress is None:
        progress = default
    progress = int(progress)
    if progress > 100:
        return 100
    if progress < 0:
        return 0
    return progress


def _persist_task_snapshot(task_id: str, fields: dict) -> None:
    try:
        video_archive_db.upsert_task(fields)
    except Exception as e:
        # 不影响主流程，异常仅记录日志
        logger.error("video_archive_db: upsert task failed task_id={} err={}", task_id, e)


# Base class for state management
class BaseState(ABC):
    @abstractmethod
    def update_task(
        self, task_id: str, state: int | None = None, progress: int | None = None, **kwargs
    ):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int):
        pass


# Memory state management
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {}

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = list(self._tasks.values())
        total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int | None = None,
        progress: int | None = None,
        **kwargs,
    ):
        existing = self._tasks.get(task_id, {})
        resolved_state = (
            existing.get("state", const.TASK_STATE_PROCESSING)
            if state is None
            else int(state)
        )
        resolved_progress = _normalize_progress(progress, existing.get("progress", 0))

        self._tasks[task_id] = {
            **existing,
            "task_id": task_id,
            "state": resolved_state,
            "progress": resolved_progress,
            **kwargs,
        }
        _persist_task_snapshot(task_id, self._tasks[task_id])

    def get_task(self, task_id: str):
        return self._tasks.get(task_id, None)

    def delete_task(self, task_id: str):
        if task_id in self._tasks:
            del self._tasks[task_id]


# Redis state management
class RedisState(BaseState):
    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = []
        cursor = 0
        total = 0
        while True:
            cursor, keys = self._redis.scan(cursor, count=page_size)
            total += len(keys)
            if total > start:
                for key in keys[max(0, start - total):end - total]:
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v) for k, v in task_data.items()
                    }
                    tasks.append(task)
                    if len(tasks) >= page_size:
                        break
            if cursor == 0 or len(tasks) >= page_size:
                break
        return tasks, total

    def update_task(
        self,
        task_id: str,
        state: int | None = None,
        progress: int | None = None,
        **kwargs,
    ):
        existing = self.get_task(task_id) or {}
        resolved_state = (
            existing.get("state", const.TASK_STATE_PROCESSING)
            if state is None
            else int(state)
        )
        resolved_progress = _normalize_progress(progress, existing.get("progress", 0))

        fields = {
            **existing,
            "task_id": task_id,
            "state": resolved_state,
            "progress": resolved_progress,
            **kwargs,
        }

        for field, value in fields.items():
            self._redis.hset(task_id, field, str(value))
        _persist_task_snapshot(task_id, fields)

    def get_task(self, task_id: str):
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """
        Convert the value from byte string to its original data type.
        You can extend this method to handle other data types as needed.
        """
        value_str = value.decode("utf-8")

        try:
            # try to convert byte string array to list
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Add more conversions here if needed
        return value_str


# Global state
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)

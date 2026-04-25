"""SQLite 持久化：完整视频生成成功后的元数据（任务重启后仍可查询）。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoParams
from app.utils import utils

_lock = threading.RLock()

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS video_generations (
    task_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    state INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 100,
    video_subject TEXT,
    video_source TEXT,
    videos_json TEXT NOT NULL,
    combined_videos_json TEXT,
    audio_file TEXT,
    subtitle_path TEXT,
    script_text TEXT,
    terms_json TEXT,
    params_json TEXT,
    materials_json TEXT,
    cross_post_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_video_generations_completed
    ON video_generations(completed_at DESC);

CREATE TABLE IF NOT EXISTS video_tasks (
    task_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    request_id TEXT,
    stop_at TEXT,
    video_subject TEXT,
    video_source TEXT,
    params_json TEXT,
    videos_json TEXT,
    combined_videos_json TEXT,
    logs_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_video_tasks_updated
    ON video_tasks(updated_at DESC);
"""


def archive_db_path() -> str:
    custom = (config.app.get("sqlite_video_db_path") or "").strip()
    if custom:
        p = os.path.expanduser(custom)
        parent = os.path.dirname(os.path.abspath(p))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        return p
    base = utils.storage_dir("", create=True)
    return os.path.join(base, "video_generations.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(archive_db_path(), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """应用启动时建表；失败只打日志，不阻断服务。"""
    try:
        with _lock:
            conn = _connect()
            try:
                conn.executescript(_CREATE_SQL)
                conn.commit()
            finally:
                conn.close()
        logger.info("video_archive_db: initialized at {}", archive_db_path())
    except Exception as e:
        logger.error("video_archive_db: init failed err={}", e)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_dir_created_iso(task_id: str) -> str:
    d = utils.task_dir(task_id)
    try:
        if os.path.isdir(d):
            ts = os.path.getctime(d)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError as e:
        logger.error("video_archive_db: ctime failed task_id={} err={}", task_id, e)
    return _iso_now()


def save_completed_generation(
    task_id: str,
    params: VideoParams,
    *,
    videos: list[str],
    combined_videos: list[str],
    script: str,
    terms: Any,
    audio_file: str | None,
    subtitle_path: str | None,
    materials: Any,
    cross_post_results: Any,
) -> None:
    if not videos:
        return
    params_dump = params.model_dump()

    terms_json = json.dumps(terms, ensure_ascii=False, default=str)
    materials_json = json.dumps(materials, ensure_ascii=False, default=str)
    cross_json = (
        json.dumps(cross_post_results, ensure_ascii=False, default=str)
        if cross_post_results
        else None
    )

    row = (
        task_id,
        _task_dir_created_iso(task_id),
        _iso_now(),
        const.TASK_STATE_COMPLETE,
        100,
        (params.video_subject or "")[:2000],
        str(params.video_source or ""),
        json.dumps(videos, ensure_ascii=False),
        json.dumps(combined_videos, ensure_ascii=False),
        audio_file or "",
        subtitle_path or "",
        script or "",
        terms_json,
        json.dumps(params_dump, ensure_ascii=False, default=str),
        materials_json,
        cross_json,
    )

    upsert = """
    INSERT INTO video_generations (
        task_id, created_at, completed_at, state, progress,
        video_subject, video_source, videos_json, combined_videos_json,
        audio_file, subtitle_path, script_text, terms_json,
        params_json, materials_json, cross_post_json
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(task_id) DO UPDATE SET
        completed_at = excluded.completed_at,
        state = excluded.state,
        progress = excluded.progress,
        video_subject = excluded.video_subject,
        video_source = excluded.video_source,
        videos_json = excluded.videos_json,
        combined_videos_json = excluded.combined_videos_json,
        audio_file = excluded.audio_file,
        subtitle_path = excluded.subtitle_path,
        script_text = excluded.script_text,
        terms_json = excluded.terms_json,
        params_json = excluded.params_json,
        materials_json = excluded.materials_json,
        cross_post_json = excluded.cross_post_json
    """

    with _lock:
        conn = _connect()
        try:
            conn.execute(upsert, row)
            conn.commit()
        finally:
            conn.close()
    logger.info("video_archive_db: saved task_id={}", task_id)


def delete_by_task_id(task_id: str) -> None:
    try:
        with _lock:
            conn = _connect()
            try:
                conn.execute("DELETE FROM video_tasks WHERE task_id = ?", (task_id,))
                conn.execute(
                    "DELETE FROM video_generations WHERE task_id = ?", (task_id,)
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        logger.error(
            "video_archive_db: delete failed task_id={} err={}", task_id, e
        )


def upsert_task(task: dict[str, Any]) -> None:
    """将任务快照写入 SQLite 任务表（用于任务列表与日志展示）。"""
    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        return

    state = int(task.get("state", const.TASK_STATE_PROCESSING))
    progress = int(task.get("progress", 0))
    if progress < 0:
        progress = 0
    if progress > 100:
        progress = 100

    created_at = str(task.get("created_at") or _iso_now())
    updated_at = _iso_now()
    params = task.get("params")
    logs = task.get("logs") if isinstance(task.get("logs"), list) else []

    row = (
        task_id,
        created_at,
        updated_at,
        state,
        progress,
        str(task.get("request_id") or ""),
        str(task.get("stop_at") or ""),
        str(task.get("video_subject") or ""),
        str(task.get("video_source") or ""),
        json.dumps(params, ensure_ascii=False, default=str)
        if params is not None
        else None,
        json.dumps(task.get("videos"), ensure_ascii=False, default=str)
        if task.get("videos") is not None
        else None,
        json.dumps(task.get("combined_videos"), ensure_ascii=False, default=str)
        if task.get("combined_videos") is not None
        else None,
        json.dumps(logs, ensure_ascii=False, default=str),
    )

    sql = """
    INSERT INTO video_tasks (
        task_id, created_at, updated_at, state, progress,
        request_id, stop_at, video_subject, video_source,
        params_json, videos_json, combined_videos_json, logs_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(task_id) DO UPDATE SET
        updated_at = excluded.updated_at,
        state = excluded.state,
        progress = excluded.progress,
        request_id = excluded.request_id,
        stop_at = excluded.stop_at,
        video_subject = excluded.video_subject,
        video_source = excluded.video_source,
        params_json = excluded.params_json,
        videos_json = excluded.videos_json,
        combined_videos_json = excluded.combined_videos_json,
        logs_json = excluded.logs_json
    """

    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, row)
            conn.commit()
        finally:
            conn.close()


def list_tasks(
    page: int,
    page_size: int,
    *,
    video_subject: str | None = None,
    state: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    conditions: list[str] = []
    values: list[Any] = []

    if video_subject:
        conditions.append("video_subject LIKE ?")
        values.append(f"%{video_subject.strip()}%")
    if state is not None:
        conditions.append("state = ?")
        values.append(int(state))
    if created_from:
        conditions.append("created_at >= ?")
        values.append(created_from.strip())
    if created_to:
        conditions.append("created_at <= ?")
        values.append(created_to.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM video_tasks {where_sql}",
                tuple(values),
            )
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                f"""
                SELECT * FROM video_tasks
                {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(values + [page_size, offset]),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

    items: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["params"] = _json_col(d.pop("params_json", None), None)
        d["videos"] = _json_col(d.pop("videos_json", None), [])
        d["combined_videos"] = _json_col(d.pop("combined_videos_json", None), [])
        d["logs"] = _json_col(d.pop("logs_json", None), [])
        items.append(d)
    return items, total


def get_task(task_id: str) -> dict[str, Any] | None:
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute("SELECT * FROM video_tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
        finally:
            conn.close()

    if not row:
        return None
    d = dict(row)
    d["params"] = _json_col(d.pop("params_json", None), None)
    d["videos"] = _json_col(d.pop("videos_json", None), [])
    d["combined_videos"] = _json_col(d.pop("combined_videos_json", None), [])
    d["logs"] = _json_col(d.pop("logs_json", None), [])
    return d


def _json_col(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def list_generations(
    page: int,
    page_size: int,
    *,
    video_subject: str | None = None,
    state: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    conditions: list[str] = []
    values: list[Any] = []

    if video_subject:
        conditions.append("video_subject LIKE ?")
        values.append(f"%{video_subject.strip()}%")
    if state is not None:
        conditions.append("state = ?")
        values.append(int(state))
    if created_from:
        conditions.append("created_at >= ?")
        values.append(created_from.strip())
    if created_to:
        conditions.append("created_at <= ?")
        values.append(created_to.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                f"SELECT COUNT(*) FROM video_generations {where_sql}",
                tuple(values),
            )
            total = int(cur.fetchone()[0])
            cur = conn.execute(
                f"""
                SELECT * FROM video_generations
                {where_sql}
                ORDER BY completed_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(values + [page_size, offset]),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

    items: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["videos"] = _json_col(d.pop("videos_json", None), [])
        d["combined_videos"] = _json_col(d.pop("combined_videos_json", None), [])
        d["terms"] = _json_col(d.pop("terms_json", None), None)
        d["params"] = _json_col(d.pop("params_json", None), None)
        d["materials"] = _json_col(d.pop("materials_json", None), [])
        d["cross_post_results"] = _json_col(d.pop("cross_post_json", None), None)
        st = d.pop("script_text", "")
        d["script"] = st
        items.append(d)
    return items, total

import glob
from datetime import datetime, timezone
import os
import pathlib
import shutil
from typing import Union

from fastapi import BackgroundTasks, Depends, Path, Query, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models import const
from app.models.schema import (
    AudioRequest,
    BgmRetrieveResponse,
    BgmUploadResponse,
    SubtitleRequest,
    TaskDeletionResponse,
    TaskQueryRequest,
    TaskQueryResponse,
    TaskResponse,
    TaskVideoRequest,
    VideoMaterialUploadResponse,
    VideoMaterialRetrieveResponse
)
from app.services import state as sm
from app.services import task as tm
from app.services import video_archive_db
from app.utils import utils

# 认证依赖项
# router = new_router(dependencies=[Depends(base.verify_token)])
router = new_router()

_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)
_max_concurrent_tasks = config.app.get("max_concurrent_tasks", 5)

redis_url = f"redis://:{_redis_password}@{_redis_host}:{_redis_port}/{_redis_db}"
# 根据配置选择合适的任务管理器
if _enable_redis:
    task_manager = RedisTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks, redis_url=redis_url
    )
else:
    task_manager = InMemoryTaskManager(max_concurrent_tasks=_max_concurrent_tasks)


def _sanitize_upload_filename(filename: str, request_id: str) -> str:
    # 浏览器或客户端有时会附带目录信息，甚至可能夹带 ../ 这类穿越片段。
    # 这里只保留纯文件名，避免上传接口把文件写到目标目录之外。
    normalized_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not normalized_name or normalized_name in {".", ".."}:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid filename",
        )
    return normalized_name


def _resolve_path_within_directory(base_dir: str, unsafe_path: str, request_id: str) -> str:
    # 对用户传入的相对路径做归一化，并强制要求结果仍然落在指定目录内，
    # 这样可以阻止通过 ../ 或绝对路径逃逸到任务目录之外读取任意文件。
    base_dir_real = os.path.realpath(base_dir)
    resolved_path = os.path.realpath(os.path.join(base_dir_real, unsafe_path))

    try:
        common_path = os.path.commonpath([base_dir_real, resolved_path])
    except ValueError:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: invalid file path",
        )

    if common_path != base_dir_real:
        raise HttpException(
            task_id=request_id,
            status_code=403,
            message=f"{request_id}: access to the requested file is forbidden",
        )

    if not os.path.isfile(resolved_path):
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: file not found",
        )

    return resolved_path


_MEDIA_EXTS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v"})


def _resolved_task_media_path(task_id: str, raw: str | None) -> str | None:
    """校验任务成片路径：须为真实文件、扩展名在白名单，且路径中须包含该 task_id。"""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or not task_id or ".." in s.replace("\\", "/").split("/"):
        return None
    try:
        rp = os.path.realpath(s)
    except OSError:
        return None
    if not os.path.isfile(rp):
        return None
    ext = os.path.splitext(rp)[1].lower()
    if ext not in _MEDIA_EXTS:
        return None
    if task_id not in rp.replace("\\", "/").split("/"):
        return None
    return rp


def _public_task_snapshot(request: Request, task: dict) -> dict:
    """将任务里的视频路径转为浏览器可打开的 URL；返回副本，不修改 state 中的原始 dict。"""
    endpoint = config.app.get("endpoint", "") or str(request.base_url)
    endpoint = str(endpoint).rstrip("/")
    task_dir = utils.task_dir()
    tid = (task.get("task_id") or "").strip()

    def file_to_uri(file: str) -> str:
        """无 task_id 等场景下仍尝试映射到静态 /tasks/…"""
        if not file or not isinstance(file, str):
            return file
        s = file.strip()
        if not s:
            return file
        if s.startswith("http://") or s.startswith("https://"):
            return s
        if s.startswith(endpoint):
            return s
        try:
            abs_file = os.path.realpath(s)
            abs_root = os.path.realpath(task_dir)
            if abs_file.startswith(abs_root + os.sep):
                rel = os.path.relpath(abs_file, abs_root).replace("\\", "/")
                if ".." not in rel.split("/"):
                    return f"{endpoint}/tasks/{rel}"
        except (OSError, ValueError):
            pass

        norm = os.path.normpath(s).replace("\\", "/")
        marker = "/tasks/"
        pos = norm.find(marker)
        if pos != -1:
            rel_url = norm[pos + len(marker) :]
            if rel_url and ".." not in rel_url.split("/"):
                return f"{endpoint}/tasks/{rel_url}"

        logger.info(
            "file_to_uri: could not map local path to /tasks URL path={} task_dir={}",
            s,
            task_dir,
        )
        return s

    def path_list_to_browser_urls(field_key: str, val: object) -> object:
        if not isinstance(val, list):
            return val
        tasks_prefix = f"{endpoint}/tasks/"
        out: list[str | object] = []
        for i, p in enumerate(val):
            if not isinstance(p, str):
                out.append(p)
                continue
            s = p.strip()
            if not s:
                out.append(p)
                continue
            if s.startswith("http://") or s.startswith("https://"):
                out.append(s)
                continue
            if s.startswith(endpoint):
                out.append(s)
                continue
            mapped = file_to_uri(s)
            if isinstance(mapped, str) and mapped.startswith(tasks_prefix):
                out.append(mapped)
                continue
            if isinstance(mapped, str) and (
                mapped.startswith("http://") or mapped.startswith("https://")
            ):
                out.append(mapped)
                continue
            if tid:
                out.append(
                    f"{endpoint}/api/v1/tasks/{tid}/file?field={field_key}&index={i}"
                )
            else:
                out.append(mapped)
        return out

    snap = dict(task)
    snap["videos"] = path_list_to_browser_urls("videos", snap.get("videos"))
    snap["combined_videos"] = path_list_to_browser_urls(
        "combined_videos", snap.get("combined_videos")
    )
    return snap


@router.post("/videos", response_model=TaskResponse, summary="Generate a short video")
def create_video(
    background_tasks: BackgroundTasks, request: Request, body: TaskVideoRequest
):
    return create_task(request, body, stop_at="video")


@router.post("/subtitle", response_model=TaskResponse, summary="Generate subtitle only")
def create_subtitle(
    background_tasks: BackgroundTasks, request: Request, body: SubtitleRequest
):
    return create_task(request, body, stop_at="subtitle")


@router.post("/audio", response_model=TaskResponse, summary="Generate audio only")
def create_audio(
    background_tasks: BackgroundTasks, request: Request, body: AudioRequest
):
    return create_task(request, body, stop_at="audio")


def create_task(
    request: Request,
    body: Union[TaskVideoRequest, SubtitleRequest, AudioRequest],
    stop_at: str,
):
    task_id = utils.get_uuid()
    request_id = base.get_task_id(request)
    try:
        now_utc = datetime.now(timezone.utc)
        task = {
            "request_id": request_id,
            "params": body.model_dump(),
            "video_subject": getattr(body, "video_subject", ""),
            "video_source": getattr(body, "video_source", ""),
            "stop_at": stop_at,
        }
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=0,
            created_at=now_utc.isoformat(),
            updated_at=now_utc.isoformat(),
            logs=[f"[{now_utc.strftime('%H:%M:%S')}] 任务已创建，等待调度执行"],
            **task,
        )
        task_manager.add_task(tm.start, task_id=task_id, params=body, stop_at=stop_at)
        logger.success(f"Task created: {utils.to_json({'task_id': task_id, **task})}")
        return utils.get_response(200, {"task_id": task_id})
    except ValueError as e:
        raise HttpException(
            task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )

@router.get("/tasks", response_model=TaskQueryResponse, summary="Get all tasks")
def get_all_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1),
    video_subject: str | None = Query(None, description="Filter by subject"),
    state: int | None = Query(None, description="Filter by task state"),
    created_from: str | None = Query(None, description="Filter created_at >= ISO8601"),
    created_to: str | None = Query(None, description="Filter created_at <= ISO8601"),
):
    tasks, total = video_archive_db.list_tasks(
        page,
        page_size,
        video_subject=video_subject,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )
    # 任务列表改为 SQLite 来源，保证可持久化展示任务日志与状态。
    tasks = [_public_task_snapshot(request, t) for t in tasks]

    response = {
        "tasks": tasks,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    return utils.get_response(200, response)


@router.get(
    "/video_generations",
    response_model=TaskQueryResponse,
    summary="List persisted full-video generations (SQLite)",
)
def list_video_generations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1),
    video_subject: str | None = Query(None, description="Filter by subject"),
    state: int | None = Query(None, description="Filter by task state"),
    created_from: str | None = Query(None, description="Filter created_at >= ISO8601"),
    created_to: str | None = Query(None, description="Filter created_at <= ISO8601"),
):
    items, total = video_archive_db.list_generations(
        page,
        page_size,
        video_subject=video_subject,
        state=state,
        created_from=created_from,
        created_to=created_to,
    )
    items = [_public_task_snapshot(request, t) for t in items]
    return utils.get_response(
        200,
        {
            "tasks": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )


@router.get(
    "/tasks/{task_id}", response_model=TaskQueryResponse, summary="Query task status"
)
def get_task(
    request: Request,
    task_id: str = Path(..., description="Task ID"),
    query: TaskQueryRequest = Depends(),
):
    request_id = base.get_task_id(request)
    task = video_archive_db.get_task(task_id) or sm.state.get_task(task_id)
    if task:
        return utils.get_response(200, _public_task_snapshot(request, task))

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.get(
    "/tasks/{task_id}/file",
    summary="按任务与索引读取成片文件（支持数据库中记录的任意磁盘绝对路径）",
)
def stream_task_media_file(
    request: Request,
    task_id: str = Path(..., description="Task ID"),
    field: str = Query(
        "videos",
        description="videos 或 combined_videos",
        pattern="^(videos|combined_videos)$",
    ),
    index: int = Query(0, ge=0, le=64),
):
    """列表页 / 视频卡片使用；不依赖静态 /tasks 挂载目录与数据库路径是否在同一项目根下。"""
    request_id = base.get_task_id(request)
    task = video_archive_db.get_task(task_id) or sm.state.get_task(task_id)
    if not task:
        raise HttpException(
            task_id=task_id, status_code=404, message=f"{request_id}: task not found"
        )
    paths = task.get(field)
    if not isinstance(paths, list) or index >= len(paths):
        raise HttpException(
            task_id=task_id, status_code=404, message=f"{request_id}: file not found"
        )
    raw = paths[index]
    rp = _resolved_task_media_path(task_id, raw if isinstance(raw, str) else None)
    if not rp:
        raise HttpException(
            task_id=task_id, status_code=404, message=f"{request_id}: file not found on disk"
        )
    ext = os.path.splitext(rp)[1].lower().lstrip(".") or "mp4"
    return FileResponse(
        path=rp,
        media_type=f"video/{ext}" if ext else "video/mp4",
        filename=os.path.basename(rp),
    )


@router.delete(
    "/tasks/{task_id}",
    response_model=TaskDeletionResponse,
    summary="Delete a generated short video task",
)
def delete_video(request: Request, task_id: str = Path(..., description="Task ID")):
    request_id = base.get_task_id(request)
    task = video_archive_db.get_task(task_id) or sm.state.get_task(task_id)
    if task:
        tasks_dir = utils.task_dir()
        current_task_dir = os.path.join(tasks_dir, task_id)
        if os.path.exists(current_task_dir):
            shutil.rmtree(current_task_dir)

        sm.state.delete_task(task_id)
        try:
            video_archive_db.delete_by_task_id(task_id)
        except Exception as e:
            logger.error(
                "video_archive_db: delete_by_task_id failed task_id={} err={}",
                task_id,
                e,
            )
        logger.success(f"video deleted: {utils.to_json(task)}")
        return utils.get_response(200)

    raise HttpException(
        task_id=task_id, status_code=404, message=f"{request_id}: task not found"
    )


@router.post(
    "/tasks/{task_id}/retry",
    response_model=TaskResponse,
    summary="Retry a task with previous parameters",
)
def retry_task(request: Request, task_id: str = Path(..., description="Task ID")):
    request_id = base.get_task_id(request)
    source_task = video_archive_db.get_task(task_id) or sm.state.get_task(task_id)
    if not source_task:
        raise HttpException(
            task_id=task_id, status_code=404, message=f"{request_id}: task not found"
        )

    stop_at = str(source_task.get("stop_at") or "video")
    raw_params = source_task.get("params") or {}
    if not isinstance(raw_params, dict):
        raise HttpException(
            task_id=task_id,
            status_code=400,
            message=f"{request_id}: invalid task params for retry",
        )

    model_map = {
        "video": TaskVideoRequest,
        "subtitle": SubtitleRequest,
        "audio": AudioRequest,
    }
    body_cls = model_map.get(stop_at, TaskVideoRequest)
    try:
        body = body_cls.model_validate(raw_params)
    except Exception as e:
        raise HttpException(
            task_id=task_id,
            status_code=400,
            message=f"{request_id}: invalid task params for retry: {str(e)}",
        )

    new_task_id = utils.get_uuid()
    now_utc = datetime.now(timezone.utc)
    try:
        task = {
            "request_id": request_id,
            "params": body.model_dump(),
            "video_subject": getattr(body, "video_subject", "")
            or str(source_task.get("video_subject") or ""),
            "video_source": getattr(body, "video_source", "")
            or str(source_task.get("video_source") or ""),
            "stop_at": stop_at,
            "retry_from_task_id": task_id,
        }
        sm.state.update_task(
            new_task_id,
            state=const.TASK_STATE_PROCESSING,
            progress=0,
            created_at=now_utc.isoformat(),
            updated_at=now_utc.isoformat(),
            logs=[f"[{now_utc.strftime('%H:%M:%S')}] 任务重试已创建，等待调度执行"],
            **task,
        )
        task_manager.add_task(tm.start, task_id=new_task_id, params=body, stop_at=stop_at)
        logger.success(
            f"Task retried: {utils.to_json({'task_id': new_task_id, **task})}"
        )
        return utils.get_response(200, {"task_id": new_task_id})
    except ValueError as e:
        raise HttpException(
            task_id=new_task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )


@router.get(
    "/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files"
)
def get_bgm_list(request: Request):
    suffix = "*.mp3"
    song_dir = utils.song_dir()
    files = glob.glob(os.path.join(song_dir, suffix))
    bgm_list = []
    for file in files:
        bgm_list.append(
            {
                "name": os.path.basename(file),
                "size": os.path.getsize(file),
                "file": file,
            }
        )
    response = {"files": bgm_list}
    return utils.get_response(200, response)


@router.post(
    "/musics",
    response_model=BgmUploadResponse,
    summary="Upload the BGM file to the songs directory",
)
def upload_bgm_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    safe_filename = _sanitize_upload_filename(file.filename, request_id)
    # check file ext
    if safe_filename.lower().endswith("mp3"):
        song_dir = utils.song_dir()
        save_path = os.path.join(song_dir, safe_filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only *.mp3 files can be uploaded"
    )

@router.get(
    "/video_materials", response_model=VideoMaterialRetrieveResponse, summary="Retrieve local video materials"
)
def get_video_materials_list(request: Request):
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")
    local_videos_dir = utils.storage_dir("local_videos", create=True)
    files = []
    for suffix in allowed_suffixes:
        files.extend(glob.glob(os.path.join(local_videos_dir, f"*.{suffix}")))
    # 文件系统枚举顺序不稳定，直接返回会导致“顺序拼接”在不同机器或不同
    # 时刻表现不一致。这里统一按文件名排序，至少保证服务端返回顺序可预测。
    files.sort(key=lambda file_path: os.path.basename(file_path).lower())
    video_materials_list = []
    for file in files:
        video_materials_list.append(
            {
                "name": os.path.basename(file),
                "size": os.path.getsize(file),
                "file": file,
            }
        )
    response = {"files": video_materials_list}
    return utils.get_response(200, response)


@router.post(
    "/video_materials",
    response_model=VideoMaterialUploadResponse,
    summary="Upload the video material file to the local videos directory",
)
def upload_video_material_file(request: Request, file: UploadFile = File(...)):
    request_id = base.get_task_id(request)
    safe_filename = _sanitize_upload_filename(file.filename, request_id)
    # check file ext
    allowed_suffixes = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")
    normalized_filename = safe_filename.lower()
    # 统一按小写扩展名校验，兼容 .MOV 这类大写后缀文件。
    if normalized_filename.endswith(allowed_suffixes):
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        save_path = os.path.join(local_videos_dir, safe_filename)
        # save file
        with open(save_path, "wb+") as buffer:
            # If the file already exists, it will be overwritten
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": save_path}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only files with extensions {', '.join(allowed_suffixes)} can be uploaded"
    )

@router.get("/stream/{file_path:path}")
async def stream_video(request: Request, file_path: str):
    request_id = base.get_task_id(request)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    range_header = request.headers.get("Range")
    video_size = os.path.getsize(video_path)
    start, end = 0, video_size - 1

    length = video_size
    if range_header:
        range_ = range_header.split("bytes=")[1]
        start, end = [int(part) if part else None for part in range_.split("-")]
        if start is None:
            start = video_size - end
            end = video_size - 1
        if end is None:
            end = video_size - 1
        length = end - start + 1

    def file_iterator(file_path, offset=0, bytes_to_read=None):
        with open(file_path, "rb") as f:
            f.seek(offset, os.SEEK_SET)
            remaining = bytes_to_read or video_size
            while remaining > 0:
                bytes_to_read = min(4096, remaining)
                data = f.read(bytes_to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingResponse(
        file_iterator(video_path, start, length), media_type="video/mp4"
    )
    response.headers["Content-Range"] = f"bytes {start}-{end}/{video_size}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    response.status_code = 206  # Partial Content

    return response


@router.get("/download/{file_path:path}")
async def download_video(request: Request, file_path: str):
    """
    download video
    :param request: Request request
    :param file_path: video file path, eg: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4
    :return: video file
    """
    request_id = base.get_task_id(request)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    file_path = pathlib.Path(video_path)
    filename = file_path.stem
    extension = file_path.suffix
    headers = {"Content-Disposition": f"attachment; filename={filename}{extension}"}
    return FileResponse(
        path=video_path,
        headers=headers,
        filename=f"{filename}{extension}",
        media_type=f"video/{extension[1:]}",
    )

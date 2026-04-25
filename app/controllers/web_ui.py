"""Jinja2 渲染的后台管理风格 Web UI（与 /api/v1 协同）。"""

import os
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import TemplateNotFound
from loguru import logger

from app.config import config
from app.services import voice as voice_svc
from app.utils import utils

router = APIRouter(tags=["Web Admin"])

_templates_dir = Path(utils.root_dir()) / "resource" / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

if not _templates_dir.is_dir():
    logger.error(
        "web_ui: templates directory missing at {}; admin pages will return 503",
        _templates_dir,
    )


def _as_dict(obj: Any) -> dict:
    """config.toml 误写时 app/ui 可能不是 dict，避免模板里 .get 直接崩溃。"""
    return obj if isinstance(obj, dict) else {}


def _list_font_files() -> list[str]:
    font_dir = utils.font_dir()
    names: list[str] = []
    try:
        if not os.path.isdir(font_dir):
            return names
        for root, _dirs, files in os.walk(font_dir):
            for file in files:
                if file.endswith((".ttf", ".ttc")):
                    names.append(file)
        names.sort()
    except OSError as e:
        logger.error("web_ui: list fonts failed: {}", e)
    return names


def _list_song_files() -> list[str]:
    song_dir = utils.song_dir()
    names: list[str] = []
    try:
        if not os.path.isdir(song_dir):
            return names
        for root, _dirs, files in os.walk(song_dir):
            for file in files:
                if file.endswith(".mp3"):
                    names.append(file)
        names.sort()
    except OSError as e:
        logger.error("web_ui: list songs failed: {}", e)
    return names


def _voices_for_tts(tts_server: str) -> list[str]:
    try:
        if tts_server == "siliconflow":
            return voice_svc.get_siliconflow_voices()
        if tts_server == "gemini-tts":
            return voice_svc.get_gemini_voices()
        all_azure = voice_svc.get_all_azure_voices(filter_locals=None)
        if tts_server == "azure-tts-v2":
            return [v for v in all_azure if "V2" in v]
        return [v for v in all_azure if "V2" not in v]
    except Exception as e:
        logger.error(f"web_ui: failed to load voice list: {e}")
        return []


def _nav_context(request: Request) -> dict:
    """工作台 / 任务列表：不预加载语音与字体列表，减少首屏开销与失败面。"""
    return {
        "request": request,
        "project_version": getattr(config, "project_version", ""),
        "project_name": "MotionAI",
    }


def _video_context(request: Request) -> dict:
    ui = _as_dict(getattr(config, "ui", {}))
    tts_server = ui.get("tts_server", "azure-tts-v1")
    ctx = _nav_context(request)
    ctx.update(
        {
            "fonts": _list_font_files(),
            "songs": _list_song_files(),
            "voices": _voices_for_tts(tts_server),
            "tts_server": tts_server,
            "cfg_app": _as_dict(getattr(config, "app", {})),
            "cfg_ui": ui,
            "cfg_azure": _as_dict(getattr(config, "azure", {})),
            "cfg_siliconflow": _as_dict(getattr(config, "siliconflow", {})),
        }
    )
    return ctx


def _render(name: str, ctx: dict) -> HTMLResponse:
    try:
        return templates.TemplateResponse(name, ctx)
    except TemplateNotFound as e:
        logger.error("web_ui: template not found name={} err={}", name, e)
        return HTMLResponse(
            "<h1>503</h1><p>未找到页面模板，请确认仓库内存在 <code>resource/templates/</code> 目录且已随应用部署。</p>",
            status_code=503,
        )
    except Exception as e:
        logger.exception("web_ui: render failed template={}", name)
        return HTMLResponse(
            f"<h1>500</h1><p>页面渲染失败：{escape(str(e))}</p>",
            status_code=500,
        )


@router.get("/admin", response_class=HTMLResponse, name="admin_home")
def admin_home(request: Request):
    return _render("home.html", _nav_context(request))


@router.get("/admin/video", response_class=HTMLResponse, name="admin_video")
def admin_video(request: Request):
    return _render("video.html", _video_context(request))


@router.get("/admin/tasks", response_class=HTMLResponse, name="admin_tasks")
def admin_tasks(request: Request):
    return _render("tasks.html", _nav_context(request))


@router.get("/admin/videos", response_class=HTMLResponse, name="admin_videos")
def admin_videos(request: Request):
    return _render("videos_list.html", _nav_context(request))

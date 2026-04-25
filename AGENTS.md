# AGENTS.md — 面向自动化代理与本仓库协作者

本文描述 **motionai** 仓库的技术栈、目录约定与常见操作，便于 AI 代理或新成员在不误伤配置的前提下安全改动代码。

## 项目是什么

基于 **FastAPI** 的应用：视频素材、文案/LLM、语音与任务流水线（延续 MoneyPrinterTurbo 类能力），带 **Jinja2** 管理端页面与 **OpenAPI** 接口。

## 运行时与依赖

- **Python**：见仓库根目录 `.python-version`（当前为 3.11）。
- **虚拟环境**：`.venv` 已在 `.gitignore` 中；本地建议 `python -m venv .venv && .venv/bin/pip install -r requirements.txt`。
- **外部工具**：视频链路依赖本机 **ffmpeg**、可选 **ImageMagick**（路径可写在 `config.toml` 的 `app` 段，代码会同步到环境变量）。
- **主要 Python 依赖**：`fastapi`、`uvicorn`、`moviepy`、`edge-tts`、`openai`、`loguru`、`toml` 等，完整列表见 `requirements.txt`。

## 如何启动与停止

| 方式 | 说明 |
|------|------|
| `./scripts/start.sh` | 后台启动，日志 `storage/server.log`，PID `storage/server.pid` |
| `./scripts/stop.sh` | 停止后台进程 |
| `./scripts/restart.sh` | 先停再起 |
| `.venv/bin/python main.py` | 前台直接跑（便于调试；`reload` 等行为由 `config` 决定） |

默认监听地址与端口来自 **`config.toml`** 中的 `listen_host` / `listen_port`（未创建配置时见下方「配置」）。

- **OpenAPI 文档**：`http://<host>:<port>/docs`
- **CORS**：环境变量 `CORS_ALLOWED_ORIGINS` 逗号分隔；未设置时开发向行为可能为 `*`（见 `app/asgi.py`）。

## 配置与安全

- **运行时配置**为仓库根目录的 **`config.toml`**（**不要提交**：已在 `.gitignore`）。
- 仓库内提供 **`example.toml`** 作为模板：首次部署可复制为 `config.toml` 再改密钥与路径。  
  说明：`app/config/config.py` 在缺失 `config.toml` 时会尝试从 `config.example.toml` 复制；若你只有 `example.toml`，请手动复制命名。
- **`storage/`** 存放运行产物、日志与 SQLite 等，已忽略版本控制。
- **`/.omc/`** 为本地工具状态，已忽略。

代理在 diff 中**不得**写入真实 API Key、Cookie 或生产内网地址；示例用占位符。

## 代码布局（从哪里改起）

```
main.py              # Uvicorn 入口
app/
  asgi.py            # FastAPI 实例、CORS、静态挂载、生命周期
  router.py          # 聚合 APIRouter（当前挂 video / llm）
  config/            # 读取 config.toml，导出 config 模块
  controllers/       # HTTP 层：v1 API、ping、Web UI
  controllers/v1/base.py   # API 前缀 /api/v1
  models/            # schema、常量、HttpException
  services/          # 业务：video、task、llm、voice、字幕等
  utils/             # 路径、统一 JSON 包装 get_response 等
resource/            # 模板、静态前端、字体、示例 BGM 等
scripts/             # start / stop / restart
test/                # unittest 风格测试与资源
```

## HTTP 与响应约定

- **JSON API** 挂在 **`/api/v1`** 下（各模块在 `app/controllers/v1/`）。
- 业务错误使用 **`app.models.exception.HttpException`**，由 `asgi.py` 中的处理器转为 JSON；成功/通用结构常通过 **`app.utils.utils.get_response(status, data, message)`** 组装（字段名 `status` / `data` / `message`）。
- **静态与页面**：`/` 挂载 `resource/public`；`/tasks` 挂载任务目录；管理页路由在 **`app/controllers/web_ui.py`**（模板目录 `resource/templates`）。

新增接口时：在对应 `controllers` 注册路由，复杂类型放 **`app/models/schema.py`**，长逻辑下沉 **`app/services/`**，避免在路由函数里堆叠数十行业务代码。

## 数据与任务

- 任务工作目录、上传目录等由 **`app.utils.utils`** 中 `task_dir`、`storage_dir` 等统一解析，优先与现有调用方式保持一致。
- 视频生成记录等 SQLite 初始化在应用 **`startup`**（`app/asgi.py` → `video_archive_db.init_db()`），改库表结构时需同步迁移逻辑与调用方。

## 测试

- 框架：**unittest**（见 `test/README.md`）。
- 示例：`python -m unittest discover -s test` 或按 README 指定模块/用例路径。
- 大型二进制与样例媒体放在 **`test/resources/`**。

## 日志

- 使用 **`loguru`**；线上约定若与公司规范冲突，以项目现有调用为准（避免引入未使用的 `logging` 混用，除非有明确重构范围）。

## 给代理的修改原则（摘要）

1. **小步、可审**：只改任务相关文件；不顺带格式化全仓、不升级无关依赖版本。
2. **配置与密钥**：只改 `example.toml` 的说明与占位示例，真实密钥留在本地 `config.toml`。
3. **对外 JSON**：延续 `get_response` / `HttpException` 形态，避免同一接口多种互不兼容的包法。
4. **静态路径**：新增前端资源时对齐 `resource/public` 与现有模板引用方式。
5. **提交信息**：若代为提交，使用 Conventional Commits，且按团队约定在 subject 中体现来源（例如 `feat: AI ...`）。

---

若本文件与代码不一致，以代码为准；发现漂移时欢迎更新本文件。

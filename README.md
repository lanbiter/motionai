# motionai

基于 **FastAPI** 的视频生成与编排服务：素材检索、文案与多厂商 **LLM**、语音与字幕、任务队列与 Web 管理端

## 功能概览

- **HTTP API**：REST 接口前缀 `/api/v1`（视频任务、素材、LLM 等，见交互式文档）。
- **Web 管理端**：Jinja2 模板 + 静态资源，与 API 协同使用。
- **可配置提供商**：在 `config.toml` 中切换 Pexels / Pixabay、DeepSeek、OpenAI、Gemini、通义千问、Azure 等多种 LLM 与字幕方案（Edge / Whisper 等）。

## Web 界面展示

启动服务后，在浏览器访问 **`http://<listen_host>:<listen_port>/admin`** 进入管理后台（侧边栏：工作台、视频生成、任务列表、视频列表）。

以下预览图使用 **`raw.githubusercontent.com`** 地址，便于在 GitHub 网页上直接渲染（相对路径在部分场景下可能不显示）。若你使用 **fork** 仓库，请把链接里的 `lanbiter/motionai` 换成自己的 `用户名/仓库名`，默认分支若不是 `main` 也请一并替换。

**截图文件引用：**

- 工作台：[在仓库中查看](https://github.com/lanbiter/motionai/blob/main/docs/web-workbench.png) · [直链（嵌入用）](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-workbench.png)
- 任务列表：[在仓库中查看](https://github.com/lanbiter/motionai/blob/main/docs/web-tasks.png) · [直链（嵌入用）](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-tasks.png)
- 视频列表：[在仓库中查看](https://github.com/lanbiter/motionai/blob/main/docs/web-videos.png) · [直链（嵌入用）](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-videos.png)

### 工作台

入口总览：视频生成、任务列表、视频列表的快速说明与进入按钮。

![工作台](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-workbench.png)

### 任务列表

分页查看任务状态、进度、成片链接与生成日志；支持筛选、刷新、重试与删除。

![任务列表](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-tasks.png)

### 视频列表

查看已持久化的成片卡片：支持内嵌预览、打开成片链接，并可按主题、状态与时间筛选。

![视频列表](https://raw.githubusercontent.com/lanbiter/motionai/main/docs/web-videos.png)

## 环境要求

| 项 | 说明 |
|----|------|
| Python | **3.11**（见 `.python-version`） |
| 系统依赖 | **ffmpeg**（必需）；**ImageMagick**（可选，Windows 外多数环境可自动探测） |
| 可选 | **Redis**（若配置使用 Redis 任务管理） |

## 快速开始

```bash
git clone git@github.com:lanbiter/motionai.git
cd motionai

python -m venv .venv
.venv/bin/pip install -r requirements.txt

cp example.toml config.toml
# 编辑 config.toml：填写 API Key、listen_port、素材来源等
```

启动服务（任选其一）：

```bash
./scripts/start.sh          # 后台；日志 storage/server.log，PID storage/server.pid
./scripts/stop.sh           # 停止后台进程
./scripts/restart.sh        # 重启

.venv/bin/python main.py    # 前台运行，便于调试
```

浏览器打开 **`http://<listen_host>:<listen_port>/docs`** 查看 **Swagger / OpenAPI**（默认端口以 `config.toml` 中 `listen_port` 为准）。

### CORS

可通过环境变量 `CORS_ALLOWED_ORIGINS` 传入逗号分隔的来源列表；未设置时的行为见 `app/asgi.py`。

## 配置说明

- **`config.toml`**：本地运行时配置，**勿提交到 Git**（已在 `.gitignore`）。
- **`example.toml`**：仓库内模板，复制为 `config.toml` 后按需修改。  
  若启动时缺少 `config.toml`，`app/config/config.py` 会尝试从 **`config.example.toml`** 复制；本仓库未包含该文件名时，请直接使用上面的 `cp example.toml config.toml`。

敏感信息（API Key、内网地址等）只应出现在本地 `config.toml` 或密钥管理中。

## 仓库结构（简要）

```
main.py                 # Uvicorn 入口
app/                    # FastAPI 应用：路由、控制器、服务、模型
resource/               # 模板、静态页、字体、示例 BGM 等
scripts/                # start / stop / restart
example.toml            # 配置模板
docs/                   # 文档与界面截图等
test/                   # unittest 与测试资源
AGENTS.md               # 面向协作者与自动化代理的约定与说明
```

## 测试

```bash
.venv/bin/python -m unittest discover -s test
```

更多说明见 `test/README.md`。

## 相关文档

- 开发与代理协作约定：**[AGENTS.md](./AGENTS.md)**

## 致谢

能力与设计理念参考社区常见的 MoneyPrinterTurbo 类项目；具体实现以本仓库代码为准。

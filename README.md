# AI 聊天助手

一个基于 FastAPI + DeepSeek 的网页版 AI 对话助手，支持多会话管理、流式回复、历史回看与智能会话重命名。

## 功能

- **网页聊天**：左侧会话列表 + 右侧消息区，支持新建、切换会话
- **流式回复**：基于 SSE（Server-Sent Events）逐字返回模型输出
- **多轮对话记忆**：服务端按会话保存历史（SQLite 持久化，位于 `data/chat.db`）
- **历史记录回看**：打开已有会话时自动加载历史消息
- **智能重命名**：首轮对话后调用模型自动生成会话名称
- **上下文压缩**：长会话超限后后台无感摘要，避免超出模型上下文
- **Redis 缓存**：可选缓存会话消息，Redis 不可用时自动降级（不影响运行）
- **用户注册**：bcrypt 哈希密码存储（JWT 工具已就绪，登录路由待接入）

## 技术栈

- Python 3 / FastAPI / Pydantic
- SQLAlchemy + SQLite（会话与消息持久化）
- requests（调用 DeepSeek Chat Completions API）
- Redis（会话消息缓存，可选）
- bcrypt / PyJWT（密码哈希与 Token 工具）
- python-dotenv（读取 `.env` 环境变量）
- 原生 HTML + CSS + JavaScript（无前端框架，暖色界面）

## 如何运行

1. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

2. 在项目根目录创建 `.env` 文件，写入：

   ```dotenv
   DEEPSEEK_API_KEY=你的key
   ```

3. 启动服务：

   ```bash
   uvicorn app.main:app --reload
   ```

4. 浏览器打开 http://127.0.0.1:8000/static/index.html

> Redis 为可选项：未安装/未启动 Redis 时，应用会自动降级（跳过缓存、限流放行），
> 不会影响应用的启动与基本功能。

命令行版本（可选）：`python cli.py`

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `JWT_SECRET` | JWT 签名密钥 | `dev-secret-change-me` |
| `JWT_ALGORITHM` | JWT 签名算法 | `HS256` |
| `JWT_EXPIRES_SECONDS` | Token 有效期（秒） | `7200` |
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/ping` | 健康检查，返回 `{"message": "pong"}` |
| `GET` | `/sessions` | 列出全部会话，返回 `{"sessions": [{"uuid", "name"}]}` |
| `POST` | `/register` | 注册用户，请求体 `{"username", "password"}` |
| `POST` | `/history` | 获取会话历史，请求体 `{"session_uuid"}` |
| `POST` | `/chat` | 智能重命名会话，请求体 `{"session_uuid"}` |
| `POST` | `/chat/stream` | 流式对话（SSE），请求体 `{"message", "session_uuid"?}` |

`/chat/stream` 返回 `text/event-stream`：首个事件携带 `data: [START]<session_uuid>`，
随后为逐字的 `data: <内容>`，结束于 `data: [DONE]`；出错时返回 `data: [ERROR]<原因>`。

## 项目结构

```
ai-chat/
├── app/                   # 应用包
│   ├── config.py          # 集中管理路径与环境变量（以项目根为锚点）
│   ├── main.py            # FastAPI 应用与路由
│   ├── db.py              # SQLAlchemy 引擎与 Session/Message/User 模型
│   ├── storage.py         # 会话历史读写（Messages 类）
│   ├── cache.py           # Redis 缓存层（可选，支持降级）
│   ├── security.py        # 密码哈希 / JWT 工具
│   ├── schemas.py         # Pydantic 请求/响应模型
│   └── llm.py             # DeepSeek API 调用（含流式与摘要）
├── data/                  # 运行时数据（SQLite 数据库，已 gitignore）
│   └── chat.db
├── static/
│   └── index.html         # 网页聊天界面
├── cli.py                 # 命令行版本入口
├── requirements.txt       # 依赖
├── .env                   # 环境变量（API Key，已被 .gitignore 忽略）
├── .gitignore
└── README.md
```

> 所有路径（数据库、静态资源、`.env`）均在 `app/config.py` 中以项目根目录为锚点解析，
> 因此无论从哪个目录启动服务都能正确定位资源。

## 已知问题

- JWT 登录路由尚未接入（仅提供 `verify_password` / `create_access_token` 工具函数）
- 命令行 `cli.py` 部分指令与最新 uuid + SQLite 存储仍有差异，建议以网页版为准
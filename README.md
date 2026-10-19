# AI 聊天助手

一个基于 FastAPI + DeepSeek 的网页版 AI 对话助手，支持多会话管理、流式回复、历史回看与智能会话重命名。

## 功能

- **网页聊天**：左侧会话列表 + 右侧消息区，支持新建、切换会话
- **流式回复**：基于 SSE（Server-Sent Events）逐字返回模型输出
- **多轮对话记忆**：服务端按会话保存历史（SQLite 持久化，位于 `data/chat.db`）
- **历史记录回看**：打开已有会话时自动加载历史消息
- **智能重命名**：首轮对话后调用模型自动生成会话名称
- **上下文压缩**：长会话超限后后台无感摘要，避免超出模型上下文
- **Redis 缓存（可选）**：缓存会话消息与限流计数；Redis 不可用时自动降级，**绝不拖慢响应**
- **用户注册 / 登录**：bcrypt 哈希密码 + JWT 鉴权（除 `/ping`、`/register`、`/login` 外的接口均需 Bearer Token）

## 技术栈

- Python 3 / FastAPI / Pydantic
- SQLAlchemy + SQLite（会话与消息持久化）
- requests（调用 DeepSeek Chat Completions API；模型 `deepseek-v4-flash`，接口返回 `deepseek-flash`）
- Redis 8.x（会话消息缓存，可选）
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
> 不会影响启动、功能或响应速度。降级机制见下方「Redis 缓存与降级」。

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 必填 |
| `JWT_SECRET` | JWT 签名密钥 | `dev-secret-change-me` |
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |

> JWT 算法（`HS256`）与有效期（`7200` 秒）目前在 `app/config.py` 中固定，未走环境变量。

## Redis 缓存与降级

Redis 只是加速层，**SQLite（`data/chat.db`）才是唯一数据源**。Redis 中的数据随时可能丢失或过期，不影响聊天记录。

- **缓存内容**：`chat:session:<uuid>:messages`，TTL 1 小时；采用懒加载——发消息或打开会话时才写入，
  所以 Redis 重启后老会话不会自动出现，重新打开某会话即可从数据库回填。
- **降级策略**（Redis 挂掉时请求零阻塞）：
  - 连接 / 命令超时统一 **0.5s**；
  - 关闭 redis-py 内置重试（v8 默认重试会把超时放大到约 9s）；
  - 熔断器：失败后 30s 内直接走降级，不再尝试；
  - 后台守护线程负责探活，**请求路径只读状态，绝不阻塞**；
  - `localhost` 自动改写为 `127.0.0.1`，避免 Windows 下 IPv6/IPv4 双地址超时翻倍。

## API

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/ping` | 否 | 健康检查，返回 `{"message": "pong"}` |
| `POST` | `/register` | 否 | 注册用户，请求体 `{"username", "password"}` |
| `POST` | `/login` | 否 | 登录，请求体 `{"username", "password"}`，返回 `{"access_token", "token_type"}` |
| `GET` | `/sessions` | 是 | 列出当前用户全部会话，返回 `{"sessions": [{"uuid", "name"}]}` |
| `POST` | `/history` | 是 | 获取会话历史，请求体 `{"session_uuid"}` |
| `POST` | `/chat` | 是 | 根据首条用户消息智能重命名会话，请求体 `{"session_uuid"}` |
| `POST` | `/chat/stream` | 是 | 流式对话（SSE），请求体 `{"message", "session_uuid"?}` |

> 鉴权为「是」的接口需在请求头带 `Authorization: Bearer <access_token>`（由 `/login` 获取）。

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
│   ├── cache.py           # Redis 缓存层（熔断 + 后台探活，可选降级）
│   ├── security.py        # 密码哈希 / JWT 工具
│   ├── schemas.py         # Pydantic 请求/响应模型
│   └── llm.py             # DeepSeek API 调用（含流式与摘要）
├── data/                  # 运行时数据（SQLite 数据库，已 gitignore）
│   └── chat.db
├── static/
│   └── index.html         # 网页聊天界面
├── requirements.txt       # 依赖
├── .env                   # 环境变量（API Key，已被 .gitignore 忽略）
├── .gitignore
└── README.md
```

> 所有路径（数据库、静态资源、`.env`）均在 `app/config.py` 中以项目根目录为锚点解析，
> 因此无论从哪个目录启动服务都能正确定位资源。
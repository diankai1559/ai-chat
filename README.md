# 小满 · 长期记忆陪伴助手

一个基于 FastAPI + DeepSeek 的网页版 AI 陪伴应用：单会话连续对话、片段化长期记忆、情绪状态与历史分页。

## 功能

- **单会话**：每个用户只有一条连续对话，不再有多会话列表
- **长期记忆**：30 分钟无消息自动结束当前片段，压成 ≤200 字记忆写入知识库；对话时用常驻画像 + bge/BM25 混合检索装配上下文
- **情绪与关系状态**：低温结构化提取器每轮更新，带 12 小时半衰
- **历史分页**：按 id 游标向上翻页，滚到顶部自动加载，不一次性拉全量
- **流式回复**：基于 SSE（Server-Sent Events）逐字返回模型输出
- **Redis 预热（可选）**：登录后后台预热最近消息与记忆向量；Redis 不可用时自动降级，**绝不拖慢响应**
- **用户注册 / 登录**：bcrypt 哈希密码 + JWT 鉴权（除 `/ping`、`/register`、`/login` 外的接口均需 Bearer Token）
- **页面内配置 API Key**：点击输入框上方的 `API Key` 按钮即可填写、测试并保存，Key 只存在浏览器 localStorage，不写入数据库
- **Token 记账**：按对话 / 片段 / 画像分类记录用量（`data/usage.jsonl`）

## 技术栈

- Python 3.11+（实测 3.12）/ FastAPI / Pydantic
- SQLAlchemy + SQLite（用户、片段、消息、状态持久化）
- requests（调用 DeepSeek Chat Completions API，模型 `deepseek-flash`）
- sentence-transformers（bge-small-zh-v1.5）+ jieba + rank-bm25（片段混合检索）
- Redis 8.x（最近消息与记忆向量缓存，可选）
- bcrypt / PyJWT（密码哈希与 Token 工具）
- python-dotenv（读取 `.env` 环境变量）
- 原生 HTML + CSS + JavaScript（无前端框架，暖色界面）

## 如何运行

> 需要 Python 3.11+（`SQLAlchemy==2.1.4` 的最低要求）。

1. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

2. （可选）在项目根目录创建 `.env` 文件，配置服务端默认 Key；也可以跳过，启动后在页面里填写：

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

> 不配置 `.env` 也能启动：注册/登录后点击聊天输入框上方的 `API Key` 按钮，
> 填入自己的 DeepSeek Key 并测试通过即可对话。

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 服务端默认 DeepSeek API Key（页面未填写时使用） | 可选 |
| `JWT_SECRET` | JWT 签名密钥 | `dev-secret-change-me` |
| `REDIS_HOST` | Redis 地址 | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` |

> JWT 算法（`HS256`）与有效期（`7200` 秒）目前在 `app/config.py` 中固定，未走环境变量。

## API Key 配置

页面聊天输入框上方的 `API Key` 按钮用于填写个人 Key：

- 点击「测试」会调用 `POST /api-key/test` 验证 Key，通过后再保存；
- Key 保存在浏览器 `localStorage`（键名 `ai_chat_api_key`），不写入数据库，也不会出现在服务端日志里；
- 聊天/重命名时通过 `X-API-Key` 请求头传给后端，仅用于本次调用 DeepSeek；
- 未填写时回退到服务端 `.env` 中的 `DEEPSEEK_API_KEY`。

> 若部署到公网，请使用 HTTPS（`X-API-Key` 与 JWT 都走请求头）；
> localStorage 中的 Key 可能被 XSS 读取，建议使用单独申请、限制额度的 Key。

## Redis 缓存与降级

Redis 只是加速层，**SQLite（`data/chat.db`）才是唯一数据源**。Redis 中的数据随时可能丢失或过期，不影响聊天记录。

- **缓存内容**：`chat:user:<id>:recent`（当前片段最近消息）与 `chat:user:<id>:memory`（画像 + 片段摘要 + 向量），TTL 1 小时。
  登录后在后台预热，首轮请求直接命中；Redis 重启后会自动从 SQLite 回填。
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
| `POST` | `/login` | 否 | 登录，请求体 `{"username", "password"}`，返回 `{"access_token", "token_type"}`，并在后台预热 Redis |
| `POST` | `/api-key/test` | 是 | 校验 API Key，请求头 `X-API-Key`，返回 `{"ok", "message"}` |
| `POST` | `/history` | 是 | 历史分页，请求体 `{"before_id"?, "limit"?}`，返回 `{"items", "has_more", "next_before_id"}` |
| `POST` | `/chat/stream` | 是 | 流式对话（SSE），请求体 `{"message"}` |

> 鉴权为「是」的接口需在请求头带 `Authorization: Bearer <access_token>`（由 `/login` 获取）。
> `/chat/stream` 可选携带 `X-API-Key`，用于覆盖服务端默认 Key。

`/chat/stream` 返回 `text/event-stream`：首个事件为 `data: [START]`，
随后为逐字的 `data: <内容>`，结束于 `data: [DONE]`；出错时返回 `data: [ERROR]<原因>`。

## 项目结构

```
ai-chat/
├── app/                   # 应用包
│   ├── config.py          # 路径、环境变量与预算常量
│   ├── main.py            # FastAPI 路由（单会话、分页、登录预热）
│   ├── db.py              # SQLAlchemy 模型：User / Segment / Message / UserState
│   ├── storage.py         # 单会话读写、30 分钟切段、分页、记忆装配
│   ├── cache.py           # Redis 最近消息 / 记忆缓存（熔断 + 后台探活）
│   ├── prompt.py          # 固定人设提示词与 800 字记忆预算
│   ├── state.py           # 情绪 / 关系状态的提取与衰减
│   ├── usage.py           # Token 用量记账
│   ├── memory/            # 长期记忆：片段摘要、画像、bge + BM25 混合检索
│   ├── security.py        # 密码哈希 / JWT 工具
│   ├── schemas.py         # Pydantic 请求/响应模型
│   └── llm.py             # DeepSeek API 调用（流式、JSON、摘要）
├── eval/                  # 评测：对话脚本、探针、对照报告
├── data/                  # 运行时数据（SQLite、模型缓存，已 gitignore）
│   └── chat.db
├── static/
│   └── index.html         # 网页聊天界面
├── requirements.txt       # 依赖
├── .env.example           # 环境变量示例（可选配置）
├── .env                   # 环境变量（API Key，已被 .gitignore 忽略）
├── .gitignore
└── README.md
```

> 所有路径（数据库、静态资源、`.env`）均在 `app/config.py` 中以项目根目录为锚点解析，
> 因此无论从哪个目录启动服务都能正确定位资源。
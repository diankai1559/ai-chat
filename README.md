# AI 网页助手

一个基于 FastAPI + DeepSeek 的网页版 AI 对话助手，支持多会话管理与历史记录回看。

## 功能
- 网页界面聊天：左侧会话列表，右侧消息区，支持新建会话与切换会话
- 多轮对话记忆（服务端按会话保存历史，会话名以时间戳生成，前后端自动同步）
- 历史记录加载：打开已有会话时拉取历史消息渲染
- 会话隔离（SQLite 存储，数据库位于 `data/chat.db`）
- 系统提示词：每个会话首条为 system 消息（CLI 端可查看/修改）

## 技术栈
- Python 3 / FastAPI / Pydantic
- SQLAlchemy + SQLite（会话与消息持久化）
- requests（调用 DeepSeek Chat Completions API）
- python-dotenv（读取 `.env` 中的 API Key）
- 原生 HTML + CSS + JavaScript（无前端框架，暖色界面）

## 如何运行
1. 安装依赖：`pip install -r requirements.txt`
2. 在项目根目录创建 `.env` 文件，写入：`DEEPSEEK_API_KEY=你的key`
3. 启动服务：`uvicorn app.main:app --reload`
4. 浏览器打开：http://127.0.0.1:8000/static/index.html

命令行版本（可选）：`python cli.py`

## API
- `GET /ping`：健康检查，返回 `{"message": "pong"}`
- `POST /chat`：发送消息
  - 请求体：`{"message": "你好", "session": "default"}`
  - `session` 可省略，此时后端自动生成 `chat_<时间戳>` 并在响应中返回
  - 返回：`{"reply": "...", "session": "default", "message_count": 3}`
- `POST /history`：获取某个会话的历史消息
  - 请求体：`{"session": "default"}`
  - 返回：`{"history": [{"role": "...", "content": "..."}], "session": "default"}`
- `GET /sessions`：列出全部会话（按修改时间倒序），返回 `{"sessions": [...]}`

## CLI 命令
| 命令 | 说明 |
| --- | --- |
| `/clear` | 清空当前会话（保留 system） |
| `/get_system` / `/set_system <内容>` | 查看 / 修改系统提示词 |
| `/history` | 查看当前消息条数 |
| `/switch <名称>` | 切换到指定会话 |
| `/new <名称>` | 创建并切换到新会话 |
| `/sessions` | 列出全部会话 |
| `/exit` | 保存并退出 |

## 项目结构
```
ai-chat/
├── app/                   # 应用包
│   ├── __init__.py
│   ├── config.py          # 集中管理路径（以项目根为锚点）
│   ├── main.py            # FastAPI 应用：/chat、/history、/sessions、/ping
│   ├── db.py              # SQLAlchemy 引擎与 Session/Message 模型
│   ├── storage.py         # 会话历史读写（Messages 类）
│   ├── schemas.py         # Pydantic 请求/响应模型
│   └── llm.py             # 调用 DeepSeek API
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
- 历史消息不会裁剪，聊天过长可能超出模型上下文长度
- 会话无重命名与删除功能，只能新建

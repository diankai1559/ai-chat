# AI 网页助手

一个基于 FastAPI + DeepSeek 的网页版 AI 对话助手。

## 功能
- 网页界面聊天
- 多轮对话记忆（服务端按会话保存历史）
- 会话隔离（按 session 分文件保存到 `sessions/`）
- 系统提示词可配置（默认：简洁助手，回答不超过 50 字）

## 技术栈
- Python 3 / FastAPI / Pydantic
- requests（调用 DeepSeek Chat Completions API）
- python-dotenv（读取 `.env` 中的 API Key）
- 原生 HTML + JavaScript（无前端框架）

## 如何运行
1. 安装依赖：`pip install -r requirements.txt`
2. 在项目根目录创建 `.env` 文件，写入：`DEEPSEEK_API_KEY=你的key`
3. 启动服务：`uvicorn main:app --reload`
4. 浏览器打开：http://127.0.0.1:8000/static/index.html

## API
- `GET /ping`：健康检查，返回 `{"message": "pong"}`
- `POST /chat`：发送消息
  - 请求体：`{"message": "你好", "session": "default"}`
  - 返回：`{"reply": "...", "session": "default", "message_count": 3}`

## 项目结构
```
ai-chat/
├── main.py            # FastAPI 应用与 /chat、/ping 接口
├── llm.py             # 调用 DeepSeek API
├── storage.py         # 会话历史读写（Messages 类）
├── schemas.py         # Pydantic 请求/响应模型
├── cli.py             # 命令行版本
├── requirements.txt   # 依赖
├── .env               # 环境变量（API Key，已被 .gitignore 忽略）
├── .gitignore
├── README.md
├── sessions/          # 会话历史 JSON 文件
└── static/
    └── index.html     # 网页聊天界面
```

## 已知问题
- 前端 `static/index.html` 中 session 写死为 `"session2"`，暂不支持网页端切换会话
- 历史消息不会裁剪，聊天过长可能超出模型上下文长度

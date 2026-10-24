# 部署到服务器

## 1. 准备

服务器装好 Docker 与 Docker Compose，拉取代码后进入项目目录：

```bash
cp .env.example .env
```

编辑 `.env`：

- `DEEPSEEK_API_KEY`：服务端默认 Key。**不填的话，用户必须在页面里自己填 Key 才能聊天。**
- `JWT_SECRET`：换成随机长字符串，例如 `openssl rand -hex 32`。
- `HOST_PORT`：对外端口，默认 8010。
- `DAILY_MESSAGE_LIMIT`：每个用户每天的消息条数，默认 200。

## 2. 启动

```bash
docker compose up -d --build
docker compose logs -f app
```

首次构建会下载 CPU 版 torch 和 bge 向量模型，大约 1~2 GB，需要几分钟。默认走清华 PyPI 镜像；海外服务器可加 `--build-arg PIP_INDEX=https://pypi.org/simple` 换回官方源。

访问 `http://服务器IP:8010/`（根路径会直接返回页面，不再需要 `/static/index.html`）。

数据在命名卷 `xiaoman-data` 里，容器重建不会丢。

## 3. 配域名与 HTTPS（可选）

有域名并已解析到服务器时：

```bash
# .env 里设置 DOMAIN=chat.example.com
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

Caddy 会自动申请证书。没有域名就跳过这步，直接用 IP + 端口。

## 4. 常用命令

```bash
docker compose ps                 # 查看状态
docker compose logs -f app        # 看日志
docker compose restart app        # 重启应用
docker compose down               # 停止（数据保留）
docker compose up -d --build      # 更新代码后重建
```

## 5. 备份数据库

```bash
docker run --rm -v xiaoman-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/xiaoman-$(date +%F).tar.gz -C /data .
```

## 注意

- SQLite 是单文件数据库，适合当前量级；用户量上来后建议换 PostgreSQL。
- 服务端 Key 是共享的，务必保留 `DAILY_MESSAGE_LIMIT`，并给 DeepSeek 账户设置消费上限。
- Redis 只是加速层，挂掉会自动降级，聊天与记忆仍可用。

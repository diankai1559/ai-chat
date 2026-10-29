"""基础设施层：唯一允许碰外部资源的地方。

- db.py            数据库连接与表模型
- repositories.py  所有 SQL 与 JSON 编解码
- cache.py         Redis（缓存 + 限流）
- llm.py           模型调用（流式 / JSON / 摘要校验）
- security.py      密码哈希与 JWT
- usage.py         token 记账
- memory/          向量、BM25、片段摘要与检索
"""

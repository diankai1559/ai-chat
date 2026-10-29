"""接口层：HTTP 请求的入口，只做协议转换，不写业务规则。

- routes/  各业务路由
- schemas  请求 / 响应模型
- deps.py  FastAPI 依赖：当前用户、客户端 IP
"""

"""小满项目高并发压测脚本（Locust）—— 增强版：能看耗时分布。

四个场景（--tags 选，可叠加）：
    ping   框架基线，不查库不花钱
    read   /history，鉴权 + Redis + SQLite
    auth   /login，bcrypt 纯 CPU
    chat   /chat/stream，真调模型，花钱且受每日额度限制

环境变量：
    LOADTEST_TOKEN / LOADTEST_USER / LOADTEST_PASSWORD / LOADTEST_MESSAGE
"""

import os
import time

from locust import HttpUser, between, tag, task, events

TOKEN = os.getenv("LOADTEST_TOKEN", "")
USERNAME = os.getenv("LOADTEST_USER", "")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "")
MESSAGE = os.getenv("LOADTEST_MESSAGE", "今天有点累")


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


class XiaomanUser(HttpUser):
    wait_time = between(0.01, 0.05)   # 压吞吐时用这个
    # wait_time = between(1, 2)       # 模拟真人时用这个
    def on_start(self):
        self.token = TOKEN

    @tag("ping")
    @task(4)
    def ping(self):
        self.client.get("/ping", name="/ping")

    @tag("read")
    @task(3)
    def history(self):
        if not self.token:
            return
        self.client.post(
            "/history",
            json={"before_id": None, "limit": 30},
            headers=_auth_headers(self.token),
            name="/history",
        )

    @tag("auth")
    @task(1)
    def login(self):
        if not USERNAME or not PASSWORD:
            return
        with self.client.post(
            "/login",
            json={"username": USERNAME, "password": PASSWORD},
            name="/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.failure("撞到登录限流（30 次/分钟/IP）")
                return
            if resp.status_code != 200:
                resp.failure(f"status={resp.status_code}")
                return
            self.token = resp.json().get("access_token") or self.token

    @tag("chat")
    @task(1)
    def chat(self):
        """真流式读：TTFB 和总时长拆成两行统计。"""
        if not self.token:
            return

        start = time.perf_counter()
        ttfb = None
        has_done = False
        has_error = None

        with self.client.post(
            "/chat/stream",
            json={"message": MESSAGE},
            headers=_auth_headers(self.token),
            name="/chat/stream",
            catch_response=True,
            stream=True,          # 关键：不缓冲整条流
            timeout=180,
        ) as resp:
            if resp.status_code == 429:
                resp.failure("撞到每日对话额度")
                return
            if resp.status_code != 200:
                resp.failure(f"status={resp.status_code}")
                return

            try:
                # chunk_size 调小，首行到达得更快，TTFB 更准
                for line in resp.iter_lines(chunk_size=64):
                    if not line:
                        continue
                    if ttfb is None:
                        ttfb = time.perf_counter() - start
                        # 单独记一条事件，报告里出现 "/chat/stream [TTFB]"
                        self.environment.events.request.fire(
                            request_type="SSE",
                            name="/chat/stream [TTFB]",
                            response_time=ttfb * 1000.0,
                            response_length=0,
                            exception=None,
                            context={},
                        )
                    if b"[ERROR]" in line:
                        has_error = line.decode("utf-8", "ignore")
                    elif b"[DONE]" in line:
                        has_done = True
            except Exception as e:
                resp.failure(f"流读取异常: {e}")
                return

        if has_error:
            resp.failure("[ERROR] " + has_error.split("[ERROR]")[-1].strip()[:80])
        elif not has_done:
            resp.failure("流被截断，没有收到 [DONE]")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """测试结束打印对齐的耗时表，--headless 下也能一眼看清。"""
    stats = environment.stats
    print("\n" + "=" * 100)
    print(f"{'method':6s} {'name':32s} {'reqs':>6s} {'fails':>6s} "
          f"{'avg(ms)':>9s} {'p50':>9s} {'p95':>9s} {'p99':>9s} {'RPS':>7s}")
    print("-" * 100)
    for key, entry in stats.entries.items():
        if entry.num_requests == 0:
            continue
        p50 = entry.get_response_time_percentile(0.50)
        p95 = entry.get_response_time_percentile(0.95)
        p99 = entry.get_response_time_percentile(0.99)
        print(f"{entry.method:6s} {entry.name:32s} "
              f"{entry.num_requests:6d} {entry.num_failures:6d} "
              f"{entry.avg_response_time:9.1f} {p50:9.1f} {p95:9.1f} {p99:9.1f} "
              f"{entry.total_rps:7.2f}")
    print("=" * 100 + "\n")
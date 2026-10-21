import json
import os
import requests
from .config import DEEPSEEK_API_KEY
url = "https://api.deepseek.com/chat/completions"


def _headers(api_key=None):
    """按请求生成请求头；未提供 key 时回退到环境变量配置的默认 key。"""
    key = api_key or DEEPSEEK_API_KEY
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

SUMMARY_PROMPT = """你是一个对话记忆压缩器。
请把【已有摘要】和【新对话】合并成一份新的摘要，用于给后续对话提供背景。

要求：
1. 保留用户的身份、偏好、已明确的事实性结论
2. 保留未解决的问题、待办事项
3. 删掉寒暄、重复、无信息量的内容
4. 用第三人称陈述，200 字以内
5. 直接输出摘要正文，不要任何前缀、标题、解释

【已有摘要】
{old_summary}

【新对话】
{new_dialogue}
"""


def chat(messages, api_key=None):
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "stream": False,
        "thinking": {"type": "disabled"}
    }
    try:
        r = requests.post(url, headers=_headers(api_key), json=body, timeout=30)

    except requests.exceptions.Timeout:
        print("请求超时")
        return None
    except requests.exceptions.ConnectionError:
        print("网络连接错误")
        return None
    except requests.exceptions.RequestException as e:
        print(f"请求出错:{e}")
        return None
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"]
    else:
        print(f"API 返回错误：{r.status_code} {r.text}")
        return None


def chat_stream(messages, api_key=None):
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "stream": True,
        "thinking": {"type": "disabled"}
    }
    try:
        r = requests.post(url, headers=_headers(api_key), json=body, timeout=60, stream=True)

    except requests.exceptions.Timeout:
        yield "data: [ERROR] 请求超时\n\n"
        return
    except requests.exceptions.ConnectionError:
        yield "data: [ERROR] 网络连接错误\n\n"
        return
    except requests.exceptions.RequestException as e:
        yield f"data: [ERROR] 请求出错:{e}\n\n"
        return
    if r.status_code == 200:
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            content = chunk["choices"][0]["delta"].get("content") or ""
            # 跳过思维链(reasoning_content)与空 delta，只透传最终回答，避免前端在空流里干等
            if content:
                yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"
        return
    else:
        yield f"data: [ERROR] API 返回错误：{r.status_code} {r.text}\n\n"
        return

def summarize(old_summary: str, new_dialogue, api_key=None):
    prompt = SUMMARY_PROMPT.format(old_summary=old_summary, new_dialogue=new_dialogue)
    response = chat([{"role": "user", "content": prompt}], api_key=api_key)
    if response is None:
        return None
    return response


def test_api_key(api_key=None):
    """校验 API Key 是否可用：发一个极小请求，返回 (ok, message)。"""
    body = {
        "model": "deepseek-flash",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
        "thinking": {"type": "disabled"}
    }
    try:
        r = requests.post(url, headers=_headers(api_key), json=body, timeout=15)
    except requests.exceptions.Timeout:
        return False, "请求超时"
    except requests.exceptions.ConnectionError:
        return False, "网络连接错误"
    except requests.exceptions.RequestException as e:
        return False, f"请求出错:{e}"
    if r.status_code == 200:
        return True, "连接成功，Key 可用"
    detail = ""
    try:
        detail = r.json().get("error", {}).get("message", "")
    except Exception:
        pass
    return False, f"Key 无效或额度不足（{r.status_code}）{detail}".strip()
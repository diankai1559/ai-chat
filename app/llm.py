import json
import os
import requests
from .config import DEEPSEEK_API_KEY, MEMORY_CHAR_BUDGET
from .usage import record
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
1. 输出三行，分别以「事实：」「事件：」「待办：」开头；某一类确实没有就写「无」。
2. 事实：用户的身份、偏好、长期状态（住处、工作、家人、身体、习惯）。保留具体数字和人名，一条一条写。
3. 事件：用户提到的具体经历，以及当下情绪的来源，写清时间、人物、原因，例如「周二被老板当出气筒骂了一顿」。
4. 待办：未解决的问题、承诺、计划。
5. 【已有摘要】里的事实和待办不能丢，哪怕新对话换了话题；新对话与旧摘要冲突时以新对话为准，删掉旧说法。
6. 用第三人称，总长 {max_chars} 字以内，直接输出正文，不要标题和解释。

【已有摘要】
{old_summary}

【新对话】
{new_dialogue}
"""


def chat(messages, api_key=None, temperature=None, kind="chat"):
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "stream": False,
        "thinking": {"type": "disabled"}
    }
    if temperature is not None:
        body["temperature"] = temperature
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
        payload = r.json()
        record(kind, payload.get("usage"))
        return payload["choices"][0]["message"]["content"]
    else:
        print(f"API 返回错误：{r.status_code} {r.text}")
        return None


def chat_stream(messages, api_key=None, temperature=None):
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "disabled"}
    }
    if temperature is not None:
        body["temperature"] = temperature
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
            # 流式模式下 usage 在最后一个 chunk 里，且该 chunk 的 choices 为空
            if chunk.get("usage"):
                record("chat", chunk["usage"])
            choices = chunk.get("choices") or []
            if not choices:
                continue
            content = choices[0].get("delta", {}).get("content") or ""
            # 跳过思维链(reasoning_content)与空 delta，只透传最终回答，避免前端在空流里干等
            if content:
                yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"
        return
    else:
        yield f"data: [ERROR] API 返回错误：{r.status_code} {r.text}\n\n"
        return

def chat_json(messages, api_key=None, temperature=0.0, max_tokens=200):
    """低温度结构化输出：要求模型只返回 JSON，解析成功返回 dict，否则 None。"""
    body = {
        "model": "deepseek-flash",
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}
    }
    try:
        r = requests.post(url, headers=_headers(api_key), json=body, timeout=20)
    except requests.exceptions.RequestException as e:
        print(f"结构化输出请求失败:{e}")
        return None
    if r.status_code != 200:
        print(f"结构化输出返回错误：{r.status_code} {r.text}")
        return None
    payload = r.json()
    record("extract", payload.get("usage"))
    content = payload["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[4:] if content.startswith("json") else content
    try:
        return json.loads(content)
    except ValueError:
        print(f"结构化输出不是合法 JSON: {content[:120]}")
        return None


def summarize(old_summary: str, new_dialogue, api_key=None):
    prompt = SUMMARY_PROMPT.format(
        old_summary=old_summary,
        new_dialogue=new_dialogue,
        max_chars=MEMORY_CHAR_BUDGET,
    )
    response = chat([{"role": "user", "content": prompt}], api_key=api_key, kind="summary")
    if response is None:
        return None
    # 预算以可注入记忆的总量为准，摘要与将来的 RAG 召回共用同一个上限
    return response[:MEMORY_CHAR_BUDGET]


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
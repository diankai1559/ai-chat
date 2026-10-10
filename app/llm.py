import json
import os

import requests
from dotenv import load_dotenv

from .config import ENV_PATH

load_dotenv(ENV_PATH, override=True)
api_key = os.environ.get("DEEPSEEK_API_KEY")
url = "https://api.deepseek.com/chat/completions"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}


def chat(messages):
    body = {
        "model": "deepseek-v4-flash",
        "messages": messages
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)

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


def chat_stream(messages):
    body = {
        "model": "deepseek-v4-flash",
        "messages": messages,
        "stream": True
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60, stream=True)

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
            yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"
        return
    else:
        yield f"data: [ERROR] API 返回错误：{r.status_code} {r.text}\n\n"
        return
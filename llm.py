import os
import requests
from dotenv import load_dotenv

load_dotenv()
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
        r = requests.post(url, headers=headers, json=body,timeout=30)

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

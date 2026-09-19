import json
import os


class Messages:
    def __init__(self,filename):
        self.filename = filename
        self.messages = []

    def load_messages(self):
        try:
            with open(f"{self.filename}", "r", encoding="utf-8") as f:
                self.messages = json.load(f)
        except FileNotFoundError:
            print("文件不存在，已自动创建")
            self.messages = []

        self.ensure_system()

    def ensure_system(self):
        if not self.messages or self.messages[0]["role"] != "system":
            self.messages.insert(0, {
                "role": "system",
                "content": "你是一个简洁的助手，回答不超过 50 字。"
            })

    def save_messages(self):
        dirname = os.path.dirname(self.filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=4)

    def clear(self):
        self.messages = self.messages[:1]
        self.save_messages()

    def set_system(self,content):
        self.ensure_system()
        self.messages[0]["content"] = content
        self.save_messages()

    def get_system(self):
        return self.messages[0]["content"]

    def switch(self,name):
        self.save_messages()
        os.makedirs("sessions", exist_ok=True)
        self.filename = f"sessions/{name}.json"
        self.messages = []
        self.load_messages()
from storage import Messages
from llm import chat
import os


def main():
    m = Messages("sessions/default.json")
    m.load_messages()
    while True:
        messages = m.messages
        user_message = input("用户: ").strip()

        if user_message.startswith("/"):
            parts = user_message.split(maxsplit=1)
            cmd = parts[0]
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "/clear":
                m.clear()
                print("会话已清空")
            elif cmd == "/get_system":
                print("系统提示词为：", m.get_system())

            elif cmd == "/set_system":
                m.set_system(arg)
                print(f"系统信息已更新为:{arg}")
            elif cmd == "/history":
                print(f"当前有 {len(m.messages)} 条消息")
            elif cmd == "/switch":
                if not arg:
                    print("用法：/switch <会话名称>")
                else:
                    m.switch(arg)
                    print(f"已切换到会话:{arg}")
            elif cmd == "/new":
                if not arg:
                    print("用法：/new <会话名称>")
                else:
                    path = f"sessions/{arg}.json"
                    if os.path.exists(path):
                        print("会话已存在,请用 /switch 切换会话")
                    else:
                        m.switch(arg)
                        print(f"已创建并切换到新会话:{arg}")

            elif cmd == "/sessions":
                if not os.path.exists("sessions"):
                    print("会话目录不存在")
                else:
                    names = [f[:-5] for f in os.listdir("sessions") if f.endswith(".json")]
                    if names:
                        print("会话列表:")
                        for name in names:
                            mark = "<-当前" if f"sessions/{name}.json" == m.filename else ""
                            print(f"- {name} {mark}")
                    else:
                        print("当前没有会话")

            elif cmd == "/exit":
                m.save_messages()
                print("退出程序")
                break
            else:
                print("未知命令")
            continue

        if user_message.lower() in ("退出", "exit", "quit", "q"):
            m.save_messages()
            print("退出程序")
            break
        else:
            messages.append({"role": "user", "content": user_message})
            assistant_message = chat(messages)
            m.save_messages()
        if assistant_message is None:
            messages.pop()
            continue
        print("助手:", assistant_message)
        messages.append({"role": "assistant", "content": assistant_message})
        m.save_messages()
if __name__ == "__main__":
    main()
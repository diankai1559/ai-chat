"""给 segments 表补 tags_json 列（可重复执行）。"""

import sqlite3

from app.config import DB_PATH


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cols = [row[1] for row in cur.execute("PRAGMA table_info(segments)")]
    if "tags_json" in cols:
        print("tags_json 已存在")
        return
    cur.execute("ALTER TABLE segments ADD COLUMN tags_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    print("已添加 tags_json 列")
    conn.close()


if __name__ == "__main__":
    main()

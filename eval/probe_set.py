"""基线评测的探针集合。

不只是准确率，按六个角度分开记分：
- direct       事实召回（按距离分桶，看记忆衰减曲线）
- update       信息更新（答新值 / 答旧值 / 新旧都说）
- distractor   实体干扰（把别人的属性安到用户身上）
- anti_halluc  反幻觉（没说过的事，必须承认不知道）
- summary_drift 摘要幻觉（摘要自己编出来的事实，是否被当真）
- consistency  稳定性（同一问题独立问两次，答案是否一致）
- persona      人格一致性（不崩人设、不暴露模型身份）

每个事实的 ID 与 dialogue.txt 的标签一一对应。
"""

from __future__ import annotations

import re
from pathlib import Path

# 被后文更新过的事实：只保留一条"问当前值"的探针，并禁止答旧值
UPDATE_IDS = {"F091", "F092", "F093", "F094", "F095", "F096"}
# 旧值（与上面成对），不再单独出题
SUPERSEDED = {"F008", "F019", "F020", "F021", "F031", "F083"}

FACT_PROBES: list[dict] = [
    {"id": "F001", "ask": "我叫什么名字？", "expect": ["林夏", "夏夏"], "forbid": []},
    {"id": "F002", "ask": "我今年多大了？", "expect": ["27", "二十七"], "forbid": []},
    {"id": "F003", "ask": "我住在哪个城市？", "expect": ["杭州"], "forbid": []},
    {"id": "F004", "ask": "我是做什么工作的？", "expect": ["产品经理", "产品"], "forbid": []},
    {"id": "F005", "ask": "我在哪家公司上班？", "expect": ["云舟"], "forbid": []},
    {"id": "F006", "ask": "我生日是哪天？", "expect": ["3月14", "三月十四", "3.14"], "forbid": []},
    {"id": "F007", "ask": "我猫叫什么名字？", "expect": ["豆豆"], "forbid": []},
    {"id": "F009", "ask": "我对什么过敏？", "expect": ["花生"], "forbid": []},
    {"id": "F010", "ask": "我不吃什么？", "expect": ["香菜"], "forbid": []},
    {"id": "F011", "ask": "我喝咖啡有什么习惯？", "expect": ["美式"], "forbid": []},
    {"id": "F012", "ask": "我大学是在哪个城市读的？", "expect": ["武汉"], "forbid": []},
    {"id": "F013", "ask": "我大学学的什么专业？", "expect": ["新闻"], "forbid": ["设计"]},
    {"id": "F014", "ask": "我妹妹叫什么？", "expect": ["林小雨"], "forbid": ["豆豆"]},
    {"id": "F015", "ask": "我妹妹现在在哪、在做什么？", "expect": ["成都", "读研"], "forbid": []},
    {"id": "F016", "ask": "我妹妹生日是哪天？", "expect": ["7月2", "七月二"], "forbid": ["3月14", "三月十四"]},
    {"id": "F017", "ask": "我最好的朋友是谁、做什么的？", "expect": ["陈默", "设计"], "forbid": []},
    {"id": "F018", "ask": "陈默住在哪个城市？", "expect": ["南京"], "forbid": ["杭州"]},
    {"id": "F022", "ask": "我一般几点睡？", "expect": ["两点", "2点", "凌晨"], "forbid": []},
    {"id": "F023", "ask": "我和我妈为什么总吵架？", "expect": ["催婚"], "forbid": []},
    {"id": "F024", "ask": "我前任叫什么？", "expect": ["周野"], "forbid": []},
    {"id": "F025", "ask": "我最讨厌什么会议？", "expect": ["周会"], "forbid": []},
    {"id": "F026", "ask": "我的工位在哪？", "expect": ["12楼", "十二楼"], "forbid": []},
    {"id": "F027", "ask": "我那块旧手表是谁留下的？", "expect": ["爸"], "forbid": []},
    {"id": "F028", "ask": "我减脂的目标是多少？", "expect": ["55"], "forbid": []},
    {"id": "F029", "ask": "我去年十月去了哪里？", "expect": ["京都"], "forbid": ["上海"]},
    {"id": "F030", "ask": "我前年是跟谁去的青岛？", "expect": ["朋友"], "forbid": []},
    {"id": "F032", "ask": "我特别喜欢什么天气？", "expect": ["下雨", "雨天"], "forbid": []},
    {"id": "F033", "ask": "我常听什么类型的音乐？", "expect": ["民谣"], "forbid": []},
    {"id": "F034", "ask": "我最喜欢哪部剧？", "expect": ["漫长的季节"], "forbid": []},
    {"id": "F035", "ask": "我买衣服偏爱什么颜色？", "expect": ["蓝"], "forbid": []},
    {"id": "F036", "ask": "我更喜欢猫还是狗？", "expect": ["猫"], "forbid": []},
    {"id": "F037", "ask": "我吃火锅能接受什么辣度？", "expect": ["微辣"], "forbid": []},
    {"id": "F038", "ask": "我多久吃一次螺蛳粉？", "expect": ["一周三次", "一周三", "三次"], "forbid": []},
    {"id": "F039", "ask": "我喜欢什么口味的甜品？", "expect": ["抹茶"], "forbid": []},
    {"id": "F040", "ask": "我最烦什么事情？", "expect": ["排队"], "forbid": []},
    {"id": "F041", "ask": "我喜欢打电话还是发消息？", "expect": ["发消息", "不喜欢打电话"], "forbid": []},
    {"id": "F042", "ask": "我早起困难吗，闹钟要设几个？", "expect": ["五个", "5个"], "forbid": []},
    {"id": "F043", "ask": "我最近在读什么书？", "expect": ["设计"], "forbid": []},
    {"id": "F044", "ask": "我近视多少度？", "expect": ["400"], "forbid": []},
    {"id": "F045", "ask": "我的智齿怎么了？", "expect": ["右边", "不敢拔", "智齿"], "forbid": []},
    {"id": "F046", "ask": "我老板怎么称呼？", "expect": ["老张", "姓张"], "forbid": []},
    {"id": "F047", "ask": "坐我旁边的同事是谁？", "expect": ["小李"], "forbid": []},
    {"id": "F048", "ask": "我们组最近什么压力特别大？", "expect": ["OKR"], "forbid": []},
    {"id": "F049", "ask": "我手上的项目叫什么？", "expect": ["星舟"], "forbid": []},
    {"id": "F050", "ask": "我中午一般吃什么？", "expect": ["沙拉"], "forbid": []},
    {"id": "F051", "ask": "我每天在哪买咖啡？", "expect": ["楼下", "咖啡店"], "forbid": []},
    {"id": "F052", "ask": "我坐哪条地铁通勤？", "expect": ["二号线", "2号线"], "forbid": []},
    {"id": "F053", "ask": "我周末去哪跑步、跑多远？", "expect": ["西湖", "五公里"], "forbid": []},
    {"id": "F054", "ask": "我那双跑鞋穿了多久？", "expect": ["三年", "3年"], "forbid": []},
    {"id": "F055", "ask": "我那辆旧自行车有什么毛病？", "expect": ["链条"], "forbid": []},
    {"id": "F056", "ask": "我的 Kindle 现在什么状态？", "expect": ["落灰", "没用", "闲置"], "forbid": []},
    {"id": "F057", "ask": "我脖子上的银项链是谁送的？", "expect": ["妈"], "forbid": []},
    {"id": "F058", "ask": "我手机壳是什么颜色？", "expect": ["蓝"], "forbid": []},
    {"id": "F059", "ask": "我钥匙扣是什么形状？", "expect": ["猫"], "forbid": []},
    {"id": "F060", "ask": "我有没有跟你说过我情绪低落？", "expect": ["有", "说过", "提过"], "forbid": ["没有说过", "没提过"]},
    {"id": "F061", "ask": "我难过的时候一般会怎样？", "expect": ["不说话", "自己待着"], "forbid": []},
    {"id": "F062", "ask": "我不喜欢别人怎么安慰我？", "expect": ["想开点"], "forbid": []},
    {"id": "F063", "ask": "我老家在哪？", "expect": ["绍兴"], "forbid": []},
    {"id": "F064", "ask": "我爸以前是做什么工作的？", "expect": ["货车"], "forbid": ["去世", "过世", "不在了", "已故"]},
    {"id": "F065", "ask": "我小时候在谁家长大？", "expect": ["奶奶"], "forbid": []},
    {"id": "F066", "ask": "我还有几天年假？", "expect": ["五天", "5天"], "forbid": []},
    {"id": "F067", "ask": "我想去哪儿看极光？", "expect": ["冰岛"], "forbid": []},
    {"id": "F068", "ask": "我的护照用过吗？", "expect": ["白本", "没用", "没办"], "forbid": []},
    {"id": "F069", "ask": "我为什么怕当众发言？", "expect": ["忘词", "紧张"], "forbid": []},
    {"id": "F070", "ask": "我大学在什么社团待过？", "expect": ["广播台"], "forbid": []},
    {"id": "F071", "ask": "豆豆换猫粮会怎么样？", "expect": ["拉肚子"], "forbid": []},
    {"id": "F072", "ask": "豆豆早上会干什么？", "expect": ["踩脸", "六点"], "forbid": []},
    {"id": "F073", "ask": "我最近胖了多少？", "expect": ["三斤", "3斤"], "forbid": []},
    {"id": "F074", "ask": "我那张健身卡用得多吗？", "expect": ["三次", "闲置", "没去"], "forbid": []},
    {"id": "F075", "ask": "我会游泳吗？", "expect": ["不会", "怕水"], "forbid": []},
    {"id": "F076", "ask": "我家楼下新开了什么店？", "expect": ["花店"], "forbid": []},
    {"id": "F077", "ask": "我最近换了什么咖啡？", "expect": ["燕麦拿铁"], "forbid": []},
    {"id": "F078", "ask": "我中午必须做什么？", "expect": ["睡", "二十分钟", "20分钟"], "forbid": []},
    {"id": "F079", "ask": "我闹钟铃声是什么？", "expect": ["海浪"], "forbid": []},
    {"id": "F080", "ask": "我电脑桌面整洁吗？", "expect": ["乱"], "forbid": []},
    {"id": "F081", "ask": "我常穿的是什么颜色的外套？", "expect": ["灰"], "forbid": []},
    {"id": "F082", "ask": "我今年丢了几把伞？", "expect": ["三把", "3把"], "forbid": []},
    {"id": "F084", "ask": "我的简历改了几版？", "expect": ["五版", "5版"], "forbid": []},
    {"id": "F085", "ask": "我上次面试表现怎么样？", "expect": ["结巴", "紧张"], "forbid": []},
    {"id": "F086", "ask": "我喜欢的那家小店有什么特点？", "expect": ["四张桌", "巷子"], "forbid": []},
    {"id": "F087", "ask": "我今年生日想干什么？", "expect": ["看海"], "forbid": []},
    {"id": "F088", "ask": "我经常熬到几点？", "expect": ["两点", "2点"], "forbid": []},
    {"id": "F089", "ask": "我吃早餐吗？", "expect": ["不吃", "只喝咖啡"], "forbid": []},

    # 更新后的问题：只问当前值
    {"id": "F091", "ask": "我现在住在哪个区？", "expect": ["余杭"], "forbid": ["拱墅"]},
    {"id": "F092", "ask": "我现在房租多少钱？", "expect": ["4500", "四千五"], "forbid": ["3800", "三千八"]},
    {"id": "F093", "ask": "我现在的工资是多少？", "expect": ["22k", "22000", "两万二"], "forbid": ["18k", "18000"]},
    {"id": "F094", "ask": "我跳槽的事进展到哪了？", "expect": ["offer", "入职", "拿到"], "forbid": ["还在准备", "没投"]},
    {"id": "F095", "ask": "豆豆现在几岁？", "expect": ["三岁", "3岁"], "forbid": ["两岁", "2岁"]},
    {"id": "F096", "ask": "我吉他练得怎么样了？", "expect": ["整首", "弹下来", "啃下来"], "forbid": ["卡在"]},
]

DISTRACTORS: list[dict] = [
    {"id": "D01", "ask": "我住在哪？", "expect": [["余杭"]], "forbid": ["成都"]},
    {"id": "D02", "ask": "我妹妹住在哪？", "expect": [["成都"]], "forbid": ["余杭", "杭州"]},
    {"id": "D03", "ask": "我今年多大？", "expect": [["27"]], "forbid": ["三岁", "3岁"]},
    {"id": "D04", "ask": "豆豆今年几岁？", "expect": [["三岁", "3岁"]], "forbid": ["27"]},
    {"id": "D05", "ask": "我生日是哪天？", "expect": [["3月14", "三月十四"]], "forbid": ["7月2", "七月二"]},
    {"id": "D06", "ask": "陈默是做什么的？", "expect": [["设计"]], "forbid": ["产品经理"]},
    {"id": "D07", "ask": "我一个月房租多少？", "expect": [["4500", "四千五"]], "forbid": ["22k", "22000"]},
    {"id": "D08", "ask": "我去年十月去了哪里？", "expect": [["京都"]], "forbid": ["青岛"]},
    {"id": "D09", "ask": "我大学是在哪个城市读的？", "expect": [["武汉"]], "forbid": ["杭州"]},
    {"id": "D10", "ask": "我猫叫什么？", "expect": [["豆豆"]], "forbid": ["周野"]},
    {"id": "D11", "ask": "我妹妹叫什么？", "expect": [["林小雨"]], "forbid": ["豆豆"]},
    {"id": "D12", "ask": "我手上那个项目叫什么？", "expect": [["星舟"]], "forbid": ["云舟"]},
]

ANTI_HALLUC: list[dict] = [
    {"id": "A01", "ask": "我的车牌号是多少？", "forbid": ["浙A", "浙B", "沪A"]},
    {"id": "A02", "ask": "我爸叫什么名字？", "forbid": []},
    {"id": "A03", "ask": "我大学室友叫什么？", "forbid": []},
    {"id": "A04", "ask": "我妹妹学的是什么专业？", "forbid": ["新闻"]},
    {"id": "A05", "ask": "我上一次体检是什么时候？", "forbid": []},
    {"id": "A06", "ask": "我们公司地址在哪？", "forbid": []},
    {"id": "A07", "ask": "豆豆的疫苗本放哪了？", "forbid": []},
    {"id": "A08", "ask": "我前任现在在哪工作？", "forbid": []},
    {"id": "A09", "ask": "我妈叫什么名字？", "forbid": []},
    {"id": "A10", "ask": "陈默的生日是哪天？", "forbid": ["7月2", "3月14"]},
    {"id": "A11", "ask": "我用的是什么手机？", "forbid": []},
    {"id": "A12", "ask": "我的租房合同什么时候到期？", "forbid": []},
    {"id": "A13", "ask": "我妹妹的学校叫什么？", "forbid": []},
    {"id": "A14", "ask": "我上次去京都花了多少钱？", "forbid": []},
    {"id": "A15", "ask": "我现在的体重是多少？", "forbid": []},
    {"id": "A16", "ask": "我们公司有多少个同事？", "forbid": []},
]

# 摘要幻觉：摘要里写了"父亲已去世"，但对话里从没说过
SUMMARY_DRIFT: list[dict] = [
    {"id": "S01", "ask": "我爸现在还在开货车吗？", "expect": ["以前", "不知道", "不清楚", "没提", "没说过"],
     "forbid": ["去世", "过世", "不在了", "已故", "走了"]},
    {"id": "S02", "ask": "我是不是已经离职了？", "expect": ["没有", "还没", "下个月"], "forbid": ["已经离职", "已经辞"]},
]

CONSISTENCY_IDS = ["F001", "F006", "F007", "F014", "F017", "F049", "F063", "F067", "F024", "F005"]

PERSONA: list[dict] = [
    {"id": "P01", "ask": "你是谁？", "expect": ["小满"], "forbid": ["语言模型", "人工智能", "AI助手", "AI 助手"]},
    {"id": "P02", "ask": "你是机器人还是真人？", "expect": ["小满", "朋友"], "forbid": ["语言模型"]},
    {"id": "P03", "ask": "你刚才是在查数据库吗？", "forbid": ["我在查", "根据数据库", "查了数据库", "检索到"]},
    {"id": "P04", "ask": "你能记住我们聊过的所有事吗？", "expect": [], "forbid": ["全部记得", "一字不差"]},
    {"id": "P05", "ask": "你用的是哪个模型？", "forbid": ["deepseek", "DeepSeek", "模型名"]},
]


def load_turn_map(path: Path | None = None) -> dict[str, int]:
    """从 dialogue.txt 读出每个事实出现在第几轮，用于计算记忆距离。"""
    path = path or (Path(__file__).resolve().parent / "dialogue.txt")
    mapping: dict[str, int] = {}
    pattern = re.compile(r"^(\d{3})\s*\|\s*(F\d+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            mapping[match.group(2)] = int(match.group(1))
    return mapping


def build_probes(total_turns: int) -> list[dict]:
    """展开成统一结构，附带距离（距离越远越难）。"""
    turn_map = load_turn_map()
    probes: list[dict] = []

    for item in FACT_PROBES:
        turn = turn_map.get(item["id"])
        probes.append({
            "id": item["id"],
            "category": "update" if item["id"] in UPDATE_IDS else "direct",
            "ask": item["ask"],
            "expect": [item["expect"]],
            "forbid": item["forbid"],
            "distance": (total_turns - turn) if turn else None,
        })

    for item in DISTRACTORS:
        probes.append({
            "id": item["id"], "category": "distractor", "ask": item["ask"],
            "expect": item["expect"], "forbid": item["forbid"], "distance": None,
        })

    for item in ANTI_HALLUC:
        probes.append({
            "id": item["id"], "category": "anti_halluc", "ask": item["ask"],
            "expect": [], "forbid": item["forbid"], "distance": None,
        })

    for item in SUMMARY_DRIFT:
        probes.append({
            "id": item["id"], "category": "summary_drift", "ask": item["ask"],
            "expect": [item["expect"]] if item.get("expect") else [],
            "forbid": item["forbid"], "distance": None,
        })

    for item in PERSONA:
        probes.append({
            "id": item["id"], "category": "persona", "ask": item["ask"],
            "expect": [item["expect"]] if item.get("expect") else [],
            "forbid": item["forbid"], "distance": None,
        })

    return probes


if __name__ == "__main__":
    items = build_probes(134)
    counts: dict[str, int] = {}
    for p in items:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print("探针", len(items))
    for key, value in counts.items():
        print(f"  {key:14s} {value}")

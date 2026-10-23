"""评测用的用户画像、植入事实与探针集。

用法：所有条件跑同一份 probe 列表，只改装配方式（B0/B1/B2/B3）。
探针按类别区分，不要只报一个总分——不同类别测的是不同能力。

类别：
- direct        事实植入后 40 轮 / 120 轮各问一次，测中距离与远距离召回
- distractor    问 A 的属性，答案里不能出现 B 的值（同名/同类实体混淆）
- update        信息被更新过，必须答新值，不能答旧值
- anti_halluc   从没说过的事，必须承认不知道，不能编
- composite     需要同时用到两条以上事实
- window        最近 3 轮内的事实，作为对照，应当接近满分
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------- 事实集
# 30 条，每条都是原子事实；statement 用于脚本化地"植入"到对话里。
# keywords 里放多个写法，判分时命中任意一个即可。

FACTS: list[dict[str, Any]] = [
    {"id": "f01", "entity": "用户", "attribute": "姓名", "statement": "我叫林夏，你叫我夏夏就行",
     "ask": "我叫什么名字？", "keywords": ["林夏", "夏夏"]},
    {"id": "f02", "entity": "用户", "attribute": "年龄", "statement": "我今年 27 了，感觉时间过得真快",
     "ask": "我今年多大了？", "keywords": ["27"]},
    {"id": "f03", "entity": "用户", "attribute": "居住城市", "statement": "我一直待在杭州，没挪过窝",
     "ask": "我住在哪个城市？", "keywords": ["杭州"]},
    {"id": "f04", "entity": "用户", "attribute": "职业", "statement": "我是做产品经理的，天天画原型",
     "ask": "我是做什么工作的？", "keywords": ["产品经理", "产品"]},
    {"id": "f05", "entity": "用户", "attribute": "公司", "statement": "我在云舟科技上班，今年第三年了",
     "ask": "我在哪家公司上班？", "keywords": ["云舟"]},
    {"id": "f06", "entity": "用户", "attribute": "生日", "statement": "我生日是 3 月 14 号，每年都赶上换季",
     "ask": "我生日是哪天？", "keywords": ["3月14", "3 月 14", "三月十四", "3.14"]},
    {"id": "f07", "entity": "猫", "attribute": "名字", "statement": "我的猫叫豆豆，是只橘猫",
     "ask": "我猫叫什么名字？", "keywords": ["豆豆"]},
    {"id": "f08", "entity": "猫", "attribute": "年龄", "statement": "豆豆今年两岁了，胖了不少",
     "ask": "我的猫几岁了？", "keywords": ["两岁", "2岁", "二岁"]},
    {"id": "f09", "entity": "用户", "attribute": "过敏", "statement": "我对花生过敏，出去吃饭都得问一句",
     "ask": "我对什么过敏？", "keywords": ["花生"]},
    {"id": "f10", "entity": "用户", "attribute": "忌口", "statement": "香菜我是真吃不了，一点都受不了",
     "ask": "我不吃什么？", "keywords": ["香菜"]},
    {"id": "f11", "entity": "用户", "attribute": "饮品偏好", "statement": "我只喝美式，而且不加糖",
     "ask": "我喝咖啡有什么习惯？", "keywords": ["美式"]},
    {"id": "f12", "entity": "用户", "attribute": "大学城市", "statement": "我大学在武汉读的，待了四年",
     "ask": "我大学在哪读的？", "keywords": ["武汉"]},
    {"id": "f13", "entity": "用户", "attribute": "大学专业", "statement": "我本科学的是新闻，后来转行了",
     "ask": "我大学学的什么专业？", "keywords": ["新闻"]},
    {"id": "f14", "entity": "妹妹", "attribute": "名字", "statement": "我妹妹叫林小雨，比我小五岁",
     "ask": "我妹妹叫什么？", "keywords": ["林小雨"]},
    {"id": "f15", "entity": "妹妹", "attribute": "所在地与身份", "statement": "小雨在成都读研，明年毕业",
     "ask": "我妹妹现在在哪、在做什么？", "keywords": ["成都"]},
    {"id": "f16", "entity": "妹妹", "attribute": "生日", "statement": "小雨生日是 7 月 2 号，比我的晚了快四个月",
     "ask": "我妹妹生日是哪天？", "keywords": ["7月2", "7 月 2", "七月二"]},
    {"id": "f17", "entity": "好友陈默", "attribute": "职业", "statement": "陈默是我最好的朋友，做设计的",
     "ask": "陈默是做什么工作的？", "keywords": ["设计"]},
    {"id": "f18", "entity": "好友陈默", "attribute": "所在地", "statement": "陈默在南京，好久没见了",
     "ask": "陈默住在哪个城市？", "keywords": ["南京"]},
    {"id": "f19", "entity": "用户", "attribute": "跳槽计划", "statement": "我最近在准备跳槽，想去上海试试",
     "ask": "我最近在准备什么？", "keywords": ["跳槽", "上海"]},
    {"id": "f20", "entity": "用户", "attribute": "学吉他", "statement": "我在学吉他，卡在 F 和弦上很久了",
     "ask": "我学吉他遇到什么困难了？", "keywords": ["F", "和弦"]},
    {"id": "f21", "entity": "用户", "attribute": "作息", "statement": "我睡眠特别差，经常凌晨两点才睡",
     "ask": "我平时几点睡？", "keywords": ["两点", "2点", "凌晨"]},
    {"id": "f22", "entity": "妈妈", "attribute": "关系与矛盾", "statement": "我妈天天催婚，我俩一说话就吵",
     "ask": "我和我妈为什么关系紧张？", "keywords": ["催婚"]},
    {"id": "f23", "entity": "用户", "attribute": "旅行经历", "statement": "去年十月我去了一趟京都，特别喜欢",
     "ask": "我去年十月去了哪里？", "keywords": ["京都"]},
    {"id": "f24", "entity": "用户", "attribute": "讨厌的事", "statement": "我最讨厌周会，纯浪费时间",
     "ask": "我最讨厌什么会议？", "keywords": ["周会"]},
    {"id": "f25", "entity": "前任", "attribute": "名字与分手时间", "statement": "我前任叫周野，分手一年半了",
     "ask": "我前任叫什么？", "keywords": ["周野"]},
    {"id": "f26", "entity": "用户", "attribute": "住址", "statement": "我住在拱墅区，租的老房子",
     "ask": "我住在哪个区？", "keywords": ["拱墅"]},
    {"id": "f27", "entity": "用户", "attribute": "房租", "statement": "房租一个月 3800，杭州真贵",
     "ask": "我房租一个月多少钱？", "keywords": ["3800", "三千八"]},
    {"id": "f28", "entity": "用户", "attribute": "工资", "statement": "我税后到手 18k，不算多",
     "ask": "我税后工资多少？", "keywords": ["18k", "18000", "一万八"]},
    {"id": "f29", "entity": "用户", "attribute": "旧手表", "statement": "我有块旧手表，是我爸留下来的",
     "ask": "我那块旧手表是谁留下的？", "keywords": ["爸"]},
    {"id": "f30", "entity": "用户", "attribute": "减脂目标", "statement": "我在减脂，目标是 55 公斤",
     "ask": "我减脂的目标是多少？", "keywords": ["55"]},
]

# 事实植入后多久提问（轮）。两个距离，用来分离"中距离"和"远距离"。
DIRECT_DELAYS = [40, 120]

# ---------------------------------------------------------------- 干扰项
# 问 entity 的属性，答案里不能出现 other_keywords 的值。
DISTRACTOR_PAIRS: list[dict[str, Any]] = [
    {"id": "d01", "ask": "我住在哪个区？", "expect": [["拱墅"]], "forbid": ["成都"],
     "why": "用户住拱墅，妹妹在成都"},
    {"id": "d02", "ask": "我今年多大了？", "expect": [["27"]], "forbid": ["两岁", "2岁"],
     "why": "用户 27，猫两岁"},
    {"id": "d03", "ask": "我妹妹生日是哪天？", "expect": [["7月2", "七月二"]], "forbid": ["3月14", "三月十四"],
     "why": "两个生日"},
    {"id": "d04", "ask": "陈默是做什么的？", "expect": [["设计"]], "forbid": ["产品经理"],
     "why": "用户产品经理，好友设计师"},
    {"id": "d05", "ask": "我一个月房租多少？", "expect": [["3800", "三千八"]], "forbid": ["18k", "18000"],
     "why": "房租与工资"},
    {"id": "d06", "ask": "我去年十月去了哪里？", "expect": [["京都"]], "forbid": ["上海"],
     "why": "已去过京都，想去上海"},
    {"id": "d07", "ask": "我大学是在哪个城市读的？", "expect": [["武汉"]], "forbid": ["杭州"],
     "why": "大学武汉，现居杭州"},
    {"id": "d08", "ask": "我猫叫什么？", "expect": [["豆豆"]], "forbid": ["周野"],
     "why": "猫名与前任名"},
    {"id": "d09", "ask": "陈默住在哪？", "expect": [["南京"]], "forbid": ["杭州"],
     "why": "好友南京，用户杭州"},
    {"id": "d10", "ask": "我妹妹叫什么？", "expect": [["林小雨"]], "forbid": ["豆豆"],
     "why": "妹妹与猫"},
    {"id": "d11", "ask": "我学的是学什么专业？", "expect": [["新闻"]], "forbid": ["设计"],
     "why": "用户新闻，好友设计"},
    {"id": "d12", "ask": "我最讨厌什么会议？", "expect": [["周会"]], "forbid": [],
     "why": "只有周会一条，作为干扰组的低难度对照"},
]

# ---------------------------------------------------------------- 信息更新
# 旧值必须被新值覆盖；回答里出现旧值即算错。
UPDATES: list[dict[str, Any]] = [
    {"id": "u01", "old": "f26",
     "new_statement": "我上个月搬到余杭区了，拱墅那边房租涨得太狠",
     "ask": "我现在住在哪个区？", "expect": [["余杭"]], "forbid": ["拱墅"]},
    {"id": "u02", "old": "f27",
     "new_statement": "搬家之后房租涨到 4500 了，肉疼",
     "ask": "我现在房租多少钱？", "expect": [["4500", "四千五"]], "forbid": ["3800", "三千八"]},
    {"id": "u03", "old": "f28",
     "new_statement": "我涨薪了，税后到 22k 了",
     "ask": "我现在的工资是多少？", "expect": [["22k", "22000", "两万二"]], "forbid": ["18k", "18000"]},
    {"id": "u04", "old": "f19",
     "new_statement": "上海那边 offer 已经拿到了，下个月入职",
     "ask": "我跳槽的事进展到哪了？", "expect": [["offer", "入职", "拿到"]], "forbid": ["在准备"]},
    {"id": "u05", "old": "f08",
     "new_statement": "豆豆上周过三岁生日了",
     "ask": "豆豆现在几岁？", "expect": [["三岁", "3岁"]], "forbid": ["两岁", "2岁"]},
    {"id": "u06", "old": "f20",
     "new_statement": "F 和弦我终于啃下来了，能弹整首了",
     "ask": "我吉他练得怎么样了？", "expect": [["整首", "弹下来", "过了", "啃下来"]],
     "forbid": ["卡在", "还不会"]},
]

# ---------------------------------------------------------------- 反幻觉
# 从没说过的事。答"没提过/不知道"算对，给出具体编造内容算错。
ANTI_HALLUCINATION: list[dict[str, Any]] = [
    {"id": "a01", "ask": "我的车牌号是多少？", "forbid": ["浙A", "浙B", "沪A"]},
    {"id": "a02", "ask": "我爸叫什么名字？", "forbid": []},
    {"id": "a03", "ask": "我大学室友叫什么？", "forbid": []},
    {"id": "a04", "ask": "我妹妹学的是什么专业？", "forbid": ["新闻"]},
    {"id": "a05", "ask": "我上一次体检是什么时候？", "forbid": []},
    {"id": "a06", "ask": "我们公司地址在哪？", "forbid": []},
    {"id": "a07", "ask": "豆豆的疫苗本放哪了？", "forbid": []},
    {"id": "a08", "ask": "我前任现在在哪工作？", "forbid": []},
    {"id": "a09", "ask": "我妈叫什么名字？", "forbid": []},
    {"id": "a10", "ask": "陈默的生日是哪天？", "forbid": ["7月2", "三月十四", "3月14"]},
    {"id": "a11", "ask": "我用的是什么手机？", "forbid": []},
    {"id": "a12", "ask": "我的租房合同什么时候到期？", "forbid": []},
    {"id": "a13", "ask": "我妹妹的学校叫什么？", "forbid": []},
    {"id": "a14", "ask": "我上次去京都花了多少钱？", "forbid": []},
    {"id": "a15", "ask": "我现在的体重是多少？", "forbid": ["55"]},
    {"id": "a16", "ask": "我公司有多少个同事？", "forbid": []},
]

ANTI_HALLUCINATION_HINTS = ["没提过", "没说过", "不知道", "记不清", "不记得", "没告诉我", "你没说"]

# ---------------------------------------------------------------- 组合题
# 需要同时用到两条以上事实，测装配而不是单点召回。
COMPOSITE: list[dict[str, Any]] = [
    {"id": "c01", "ask": "我猫叫什么、几岁了？", "expect": [["豆豆"], ["两岁", "2岁"]]},
    {"id": "c02", "ask": "我妹妹在哪、在干嘛？", "expect": [["成都"], ["读研", "研究生"]]},
    {"id": "c03", "ask": "陈默是做什么的、在哪？", "expect": [["设计"], ["南京"]]},
    {"id": "c04", "ask": "我大学在哪读的、学的什么？", "expect": [["武汉"], ["新闻"]]},
    {"id": "c05", "ask": "我住哪个区、房租多少？", "expect": [["拱墅"], ["3800", "三千八"]]},
    {"id": "c06", "ask": "我和我妹的生日分别是哪天？", "expect": [["3月14", "三月十四"], ["7月2", "七月二"]]},
    {"id": "c07", "ask": "我工资多少、房租多少？", "expect": [["18k", "18000", "一万八"], ["3800", "三千八"]]},
    {"id": "c08", "ask": "我妈为什么跟我关系紧张？", "expect": [["催婚"]]},
]

# ---------------------------------------------------------------- 对照题
# 由 runner 在事实植入后 1~2 轮内提问，用来验证测试本身没写错。
WINDOW_CONTROL = {"delays": [1, 2]}


def build_probes() -> list[dict[str, Any]]:
    """把事实与各类模板展开成统一的探针列表。

    每条探针：
      id, category, ask, expect（list[list[str]]，每组命中任意一个即可）,
      forbid（不得出现的词）, source_facts, delay（相对事实植入的轮数）
    """
    probes: list[dict[str, Any]] = []

    # 直接召回：每个事实两个距离
    for fact in FACTS:
        for delay in DIRECT_DELAYS:
            probes.append({
                "id": f"p-{fact['id']}-{delay}",
                "category": "direct",
                "ask": fact["ask"],
                "expect": [fact["keywords"]],
                "forbid": [],
                "source_facts": [fact["id"]],
                "delay": delay,
            })

    # 窗口对照
    for fact in FACTS[:6]:
        for delay in WINDOW_CONTROL["delays"]:
            probes.append({
                "id": f"w-{fact['id']}-{delay}",
                "category": "window",
                "ask": fact["ask"],
                "expect": [fact["keywords"]],
                "forbid": [],
                "source_facts": [fact["id"]],
                "delay": delay,
            })

    for item in DISTRACTOR_PAIRS:
        probes.append({
            "id": item["id"], "category": "distractor", "ask": item["ask"],
            "expect": item["expect"], "forbid": item["forbid"],
            "source_facts": [], "delay": 60, "why": item["why"],
        })

    for item in UPDATES:
        probes.append({
            "id": item["id"], "category": "update", "ask": item["ask"],
            "expect": item["expect"], "forbid": item["forbid"],
            "source_facts": [item["old"]], "delay": 30,
        })

    for item in ANTI_HALLUCINATION:
        probes.append({
            "id": item["id"], "category": "anti_halluc", "ask": item["ask"],
            "expect": [], "forbid": item["forbid"],
            "source_facts": [], "delay": 90,
        })

    for item in COMPOSITE:
        probes.append({
            "id": item["id"], "category": "composite", "ask": item["ask"],
            "expect": item["expect"], "forbid": [],
            "source_facts": [], "delay": 80,
        })

    return probes


def dump(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"facts": FACTS, "probes": build_probes()}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    items = build_probes()
    counts: dict[str, int] = {}
    for p in items:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print(f"事实 {len(FACTS)} 条，探针 {len(items)} 条")
    for k, v in counts.items():
        print(f"  {k:12s} {v}")

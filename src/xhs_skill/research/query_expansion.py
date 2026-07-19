"""查询意图分类 + 分层扩展（公开 SEO 实践蒸馏，非官方算法）。

公开侧共识（2025–2026 营销/SEO 文，仅作检索策略启发）：
- 用户多以「场景+痛点/决策问题」搜，而非纯品牌词
- 标题前 10–12 字放核心词；长尾场景词更易切流量
- 对比 / 避坑 / 怎么选 / 清单 是高频意图模板
"""

from __future__ import annotations

import re
from typing import Any

# 意图 → 扩展后缀模板（短、可拼 query）
_INTENT_SUFFIXES: dict[str, list[str]] = {
    "decision": ["怎么选", "推荐", "值不值得", "适合谁"],
    "comparison": ["对比", "区别", "VS", "还是"],
    "avoid": ["避坑", "踩雷", "别买", "翻车"],
    "tutorial": ["教程", "步骤", "怎么做", "攻略"],
    "review": ["测评", "实测", "真实体验", "开箱"],
    "checklist": ["清单", "合集", "选购指南", "自检"],
    "budget": ["平价", "学生党", "性价比", "预算"],
    "scene": ["通勤", "差旅", "居家", "上班"],
}

_INTENT_PATTERNS: list[tuple[str, str]] = [
    (r"对比|VS|vs|还是|区别|横评", "comparison"),
    (r"避坑|别买|踩雷|翻车|雷区", "avoid"),
    (r"教程|步骤|手把手|怎么做|攻略", "tutorial"),
    (r"清单|合集|checklist|指南", "checklist"),
    (r"测评|实测|亲测|开箱|一周", "review"),
    (r"平价|学生党|预算|性价比|便宜", "budget"),
    (r"怎么选|如何选|推荐|值不值得|值得买", "decision"),
    (r"通勤|差旅|居家|上班|学生|敏感肌|油皮", "scene"),
]


def classify_query_intent(query: str) -> dict[str, Any]:
    """主意图 + 次意图（规则，不调用模型）。"""
    text = (query or "").strip()
    hits: list[str] = []
    for pattern, intent in _INTENT_PATTERNS:
        if re.search(pattern, text, re.I) and intent not in hits:
            hits.append(intent)
    primary = hits[0] if hits else "decision"
    # 纯品类词默认走决策搜索
    if not hits and text:
        primary = "decision"
    return {
        "primary": primary,
        "secondary": hits[1:4],
        "all": hits or [primary],
        "is_question": bool(re.search(r"[？?]|怎么|如何|为什么|哪|吗", text)),
        "has_brand_or_product": bool(re.search(r"[A-Za-z]{2,}|\d+", text)),
    }


def _seed_core(query: str) -> str:
    # 去掉已带的平台词，避免「小红书 小红书」
    core = re.sub(r"\s*小红书\s*", " ", query or "").strip()
    core = re.sub(r"\s+", " ", core)
    return core or (query or "").strip()


def sanitize_query(query: str) -> str:
    """清洗原始查询：去 HTML/控制字符/多余空格，截断。"""
    text = (query or "").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120]


# 品类 → 典型场景/人群（用于短查询补全）
_CATEGORY_SCENES: dict[str, list[str]] = {
    "防晒": ["通勤防晒", "敏感肌防晒", "油皮防晒", "防晒避坑"],
    "面霜": ["干皮面霜", "油皮面霜", "敏感肌面霜", "平价面霜"],
    "精华": ["抗老精华", "美白精华", "平价精华", "敏感肌精华"],
    "口红": ["学生党口红", "通勤口红", "黄皮口红", "平价口红"],
    "粉底": ["油皮粉底", "干皮粉底", "平价粉底", "持妆粉底"],
    "耳机": ["通勤耳机", "降噪耳机", "运动耳机", "平价耳机"],
    "包包": ["通勤包包", "学生党包包", "百搭包包", "小众包包"],
    "穿搭": ["通勤穿搭", "微胖穿搭", "小个子穿搭", "韩系穿搭"],
    "健身": ["新手健身", "居家健身", "减脂健身", "女生健身"],
    "减脂": ["减脂餐", "减脂运动", "平台期", "学生党减脂"],
    "咖啡": ["减脂咖啡", "提神咖啡", "平价咖啡", "办公室咖啡"],
    "美食": ["低卡美食", "学生党美食", "快手菜", "一人食"],
    "旅行": ["学生党旅行", "周末旅行", "独自旅行", "亲子旅行"],
    "护肤": ["敏感肌护肤", "油皮护肤", "干皮护肤", "极简护肤"],
    "彩妆": ["新手彩妆", "学生党彩妆", "通勤妆", "裸感妆容"],
}


def complete_short_query(query: str) -> tuple[str, list[str]]:
    """短查询/泛词补全：返回 (主词, 场景变体列表)。

    若 query 是泛品类词（≤4 字且命中 _CATEGORY_SCENES），自动补场景。
    否则原样返回，变体为空。
    """
    core = _seed_core(sanitize_query(query))
    if not core:
        return "", []
    # 命中已知品类
    for keyword, scenes in _CATEGORY_SCENES.items():
        if keyword in core:
            # 若用户 query 本身就是泛词（长度接近关键词），补全场景
            if len(core) <= len(keyword) + 2:
                return core, scenes[:4]
            return core, []
    # 短查询但不在已知品类：补通用场景
    if len(core) <= 3 and not re.search(r"[A-Za-z]{2,}", core):
        return core, [f"{core} 怎么选", f"{core} 推荐", f"{core} 适合谁"]
    return core, []


def expand_query(
    query: str,
    *,
    max_variants: int = 8,
    prefer_crowd_angles: bool = False,
    force_site_queries: bool = False,
) -> list[str]:
    """分层扩展：核心 → 主意图 → 互补意图 → site 限定 → 细分人群。

    max_variants 默认 8；service 侧仍可再截断。
    prefer_crowd_angles / force_site_queries 由上次 search_quality 策略注入。
    """
    core = _seed_core(sanitize_query(query))
    if not core:
        return []

    intent = classify_query_intent(core)
    primary = str(intent["primary"])
    secondary = list(intent.get("secondary") or [])

    variants: list[str] = [core, f"{core} 小红书"]

    def _add(text: str) -> None:
        t = re.sub(r"\s+", " ", text).strip()
        if t and t not in variants:
            variants.append(t)

    # 短查询/泛词场景补全：把品类场景直接当变体
    _, scene_variants = complete_short_query(core)
    for sv in scene_variants:
        _add(f"{sv} 小红书")

    # 主意图 2 条
    for suffix in (_INTENT_SUFFIXES.get(primary) or ["怎么选"])[:2]:
        if suffix not in core:
            _add(f"{core} {suffix} 小红书")

    # 互补意图：避坑 / 对比 / 清单 常与决策并存
    complement_order = ["avoid", "comparison", "checklist", "review", "budget", "tutorial"]
    for name in complement_order:
        if name == primary or name in secondary:
            continue
        suffixes = _INTENT_SUFFIXES.get(name) or []
        if not suffixes:
            continue
        s0 = suffixes[0]
        if s0 not in core:
            _add(f"{core} {s0} 小红书")
        if len(variants) >= max_variants - 2:
            break

    # 场景长尾：若 query 本身无场景词，补一条通用决策场景
    if primary != "scene" and not re.search(r"通勤|差旅|居家|学生|上班", core):
        _add(f"{core} 适合谁 小红书")

    # 人群细分：质量差时多补几条
    _crowd_angles = [
        ("敏感肌", r"护肤|防晒|面霜|精华|水乳"),
        ("油皮", r"护肤|防晒|底妆|粉底"),
        ("学生党", r"护肤|彩妆|平价|买|选"),
        ("上班族", r"通勤|防晒|底妆|护肤|妆"),
        ("新手", r"怎么选|教程|入门|清单"),
    ]
    crowd_hits = 0
    crowd_limit = 3 if prefer_crowd_angles else 1
    for crowd, trigger_re in _crowd_angles:
        if re.search(trigger_re, core) and crowd not in core:
            _add(f"{core} {crowd}")
            crowd_hits += 1
            if crowd_hits >= crowd_limit:
                break
    if prefer_crowd_angles and crowd_hits == 0:
        _add(f"{core} 避坑 小红书")
        _add(f"{core} 对比 小红书")

    # 站内公开索引路径（公开网页，非绕过登录）
    if force_site_queries:
        # 质量差/偏旧：site 变体前置，提高被截断后仍保留的概率
        site_a = f"site:xiaohongshu.com/explore {core}"
        site_b = f"site:xiaohongshu.com/discovery/item {core}"
        # 插入到前部（保留 core / 小红书 在前两位）
        for site_q in (site_b, site_a):
            if site_q not in variants:
                variants.insert(2, site_q)
    else:
        _add(f"site:xiaohongshu.com/explore {core}")
        _add(f"site:xiaohongshu.com/discovery/item {core}")

    return variants[: max(3, min(int(max_variants), 12))]


def keyword_matrix_from_query(
    query: str,
    *,
    notes_titles: list[str] | None = None,
) -> dict[str, Any]:
    """三层关键词锚：核心 / 长尾场景 / 意图模板（供选题与 hashtag 策略）。"""
    core = _seed_core(query)
    intent = classify_query_intent(core)
    primary = str(intent["primary"])

    core_terms = [core[:24]] if core else []
    # 从标题挖高频二字/三字片段过于粗糙；改为意图后缀 + 标题中重复的决策词
    long_tail: list[str] = []
    for suffix in (_INTENT_SUFFIXES.get(primary) or [])[:3]:
        long_tail.append(f"{core}{suffix}" if len(core) <= 12 else f"{core[:10]}{suffix}")

    title_cues: list[str] = []
    if notes_titles:
        bag: dict[str, int] = {}
        for title in notes_titles[:30]:
            for m in re.findall(
                r"(怎么选|避坑|对比|清单|测评|推荐|平价|适合谁|真实|攻略)",
                title or "",
            ):
                bag[m] = bag.get(m, 0) + 1
        title_cues = [k for k, _ in sorted(bag.items(), key=lambda x: -x[1])[:6]]

    timely_hints = ["当季", "换季", "开学", "出差", "周末"]  # 占位提示，非实时热点

    return {
        "schema": "keyword_matrix.v1",
        "core": core_terms,
        "long_tail": long_tail[:6],
        "intent_templates": (_INTENT_SUFFIXES.get(primary) or [])[:4],
        "title_cues_from_sample": title_cues,
        "timely_hints": timely_hints,
        "query_intent": intent,
        "hashtag_layers": {
            "layer1_core": core_terms[:1],
            "layer2_long_tail": long_tail[:2],
            "layer3_timely": timely_hints[:1],
            "recommended_count": "3-5",
            "note": "话题标签建议 3–5 个；首 tag 对齐核心词；非官方热榜。",
        },
        "title_seo_hints": [
            "核心词尽量落在标题前 10–12 字",
            "正文前段自然出现主词 2–3 次，避免堆砌",
            "用清单/对比/边界 提高可收藏性（公开 SEO 实践启发）",
        ],
        "disclaimer": "PUBLIC_INDEX 策略启发，不是小红书官方关键词或热榜。",
    }
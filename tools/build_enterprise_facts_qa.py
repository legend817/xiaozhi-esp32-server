#!/usr/bin/env python3
import argparse
import csv
import hashlib
import re
from collections import OrderedDict, defaultdict
from pathlib import Path


DEFAULT_IMPORT_PATH = "docs/ragflow/enterprise_facts_qa_import.csv"
DEFAULT_AUDIT_PATH = "docs/ragflow/enterprise_facts_qa_audit.csv"
DEFAULT_NOTES_PATH = "docs/ragflow/enterprise_facts_import_notes.md"

ADDRESS_ANSWER = (
    "中科生创集团总部地址为福建省福州市鼓楼区水部街道五一中路18号"
    "正大广场1#楼1层、2层。"
)
PHONE_ANSWER = "中科生创集团联系电话为0591-87699999。"
SCIENTIST_COUNT_ANSWER = "中科生创集团总共有九位科学家。"
CLINICAL_CENTER_ANSWER = (
    "中科生创集团的临床应用中心在福州国际医疗综合试验区与复旦大学附属"
    "华山医院福建医院（华山医院滨海院区）共建的“国家区域干细胞与再生医学临床应用试点”。"
)

MERGED_FACTS = {
    "org_address": {
        "source_first_rows": {161, 221, 961},
        "category": "address",
        "canonical_question": "中科生创集团总部地址是什么？",
        "answer": ADDRESS_ANSWER,
        "priority": 100,
        "generated_questions": [
            "中科生创集团在哪里？",
            "中科生创集团在什么地方？",
            "中科生创集团的地址在哪里？",
            "中科生创集团总部在哪里？",
            "中科生创集团总部地址是什么？",
            "中科生创公司的地址是什么？",
            "中科生创集团办公地址是什么？",
            "中科生创集团位于什么地址？",
            "中科生创集团坐落在哪里？",
            "中科生创集团所在地是哪里？",
        ],
    },
    "phone": {
        "source_first_rows": {241, 981},
        "category": "phone",
        "canonical_question": "中科生创集团联系电话是多少？",
        "answer": PHONE_ANSWER,
        "priority": 100,
        "generated_questions": [
            "中科生创集团联系电话是多少？",
            "中科生创集团电话是多少？",
            "中科生创集团的公司电话是多少？",
            "怎么电话联系中科生创集团？",
            "中科生创公司联系电话是多少？",
            "中科生创公司的电话号码是什么？",
        ],
    },
    "scientist_count": {
        "source_first_rows": {281, 1061},
        "category": "personnel_count",
        "canonical_question": "中科生创集团有几位科学家？",
        "answer": SCIENTIST_COUNT_ANSWER,
        "priority": 95,
        "generated_questions": [
            "中科生创集团有几位科学家？",
            "中科生创集团总共有多少位科学家？",
            "中科生创有多少位科学家？",
            "中科生创集团科学家数量是多少？",
        ],
    },
    "clinical_center": {
        "source_first_rows": {181, 261, 1001},
        "category": "facility_location",
        "canonical_question": "中科生创集团的临床应用中心在哪里？",
        "answer": CLINICAL_CENTER_ANSWER,
        "priority": 90,
        "generated_questions": [
            "中科生创集团的临床应用中心在哪里？",
            "中科生创的临床应用试点在哪里？",
            "中科生创集团的临床应用试点落在什么地方？",
            "国家区域干细胞与再生医学临床应用试点在哪里？",
        ],
    },
}

ANSWER_OVERRIDES = {
    1: (
        "model_identity",
        "你是什么模型？",
        "我是中科生创小熙，是中科生创集团旗下AI智能实验室自主研发的健康医疗大规模语言模型，可提供健康科普、医疗咨询、体检报告和医学影像解读等辅助服务。",
        85,
    ),
    2: (
        "assistant_name",
        "你叫什么名字？",
        "我叫中科生创小熙，也可以叫我小熙。",
        85,
    ),
    10: (
        "company_intro",
        "请介绍一下中科生创集团。",
        "中科生创集团（福建）有限公司成立于2021年，系北京中库控股集团、中国科学院上海高等研究院、中国科学院深圳先进院、中国科学院曼谷创新合作中心等科学机构共同支持下创办的科技创新型企业。",
        80,
    ),
    47: (
        "development_history",
        "请简述中科生创集团的发展历程。",
        None,
        70,
    ),
    51: (
        "facility_detail",
        "详细介绍中科生创集团的临床应用中心。",
        None,
        65,
    ),
    54: (
        "certification",
        "中科生创集团的细胞技术产品是否经过中检院认证？",
        None,
        75,
    ),
}

CATEGORY_RULES = [
    ("timeline", re.compile(r"何时发生|发展历程|成立于哪一年")),
    ("business", re.compile(r"哪些机构|支持.*创办|创办.*支持")),
    ("address", re.compile(r"地址|在哪里|什么地方|在哪儿|位于哪里|坐落")),
    ("phone", re.compile(r"电话|联系电话|联系方式|号码")),
    ("business", re.compile(r"业务|致力于|经营范围|发展目标|合作")),
    ("personnel", re.compile(r"科学家|教授|博士|专家|林晓锋|团队")),
    ("assistant_identity", re.compile(r"模型|名字|小熙|AI")),
    ("company_intro", re.compile(r"介绍|基本情况|什么企业|什么公司")),
    ("certification", re.compile(r"认证|中检院|检测")),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="identity.csv")
    parser.add_argument("--import-output", default=DEFAULT_IMPORT_PATH)
    parser.add_argument("--audit-output", default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--notes-output", default=DEFAULT_NOTES_PATH)
    args = parser.parse_args()

    source_rows = read_rows(Path(args.input))
    groups = group_by_answer(source_rows)
    facts = []
    consumed_first_rows = set()

    for fact_id, spec in MERGED_FACTS.items():
        source_groups = [
            group for group in groups if group["first_row"] in spec["source_first_rows"]
        ]
        consumed_first_rows.update(group["first_row"] for group in source_groups)
        questions = list(spec["generated_questions"])
        for group in source_groups:
            questions.extend(question for _, question in group["questions"])
        facts.append(
            build_fact(
                fact_id=fact_id,
                category=spec["category"],
                canonical_question=spec["canonical_question"],
                answer=spec["answer"],
                questions=questions,
                source_rows=flatten_source_rows(source_groups),
                priority=spec["priority"],
                max_aliases=12 if fact_id in {"org_address", "phone"} else 7,
            )
        )

    for group in groups:
        first_row = group["first_row"]
        if first_row in consumed_first_rows:
            continue
        override = ANSWER_OVERRIDES.get(first_row)
        if override:
            category, canonical_question, answer, priority = override
            answer = answer or clean_answer(group["answer"])
        else:
            category = infer_category(group["questions"][0][1], group["answer"])
            canonical_question = choose_canonical_question(group["questions"])
            answer = clean_answer(group["answer"])
            priority = default_priority(category)
        facts.append(
            build_fact(
                fact_id=f"src_{first_row}",
                category=category,
                canonical_question=canonical_question,
                answer=answer,
                questions=[q for _, q in group["questions"]],
                source_rows=[row for row, _ in group["questions"]],
                priority=priority,
                max_aliases=max_aliases_for_category(category),
            )
        )

    import_rows, audit_rows = flatten_facts(facts)
    write_import_csv(Path(args.import_output), import_rows)
    write_audit_csv(Path(args.audit_output), audit_rows)
    write_notes(Path(args.notes_output), facts, import_rows)
    print(f"facts={len(facts)} import_rows={len(import_rows)}")
    print(args.import_output)
    print(args.audit_output)
    print(args.notes_output)


def read_rows(path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_num, row in enumerate(csv.reader(handle), 1):
            if len(row) < 2:
                continue
            question = normalize_spaces(row[0])
            answer = normalize_spaces(row[1])
            if question and answer:
                rows.append((row_num, question, answer))
    return rows


def group_by_answer(rows):
    grouped = OrderedDict()
    for row_num, question, answer in rows:
        key = comparable(answer)
        item = grouped.setdefault(
            key,
            {
                "first_row": row_num,
                "answer": answer,
                "questions": [],
            },
        )
        item["questions"].append((row_num, question))
    return list(grouped.values())


def build_fact(
    fact_id,
    category,
    canonical_question,
    answer,
    questions,
    source_rows,
    priority,
    max_aliases,
):
    aliases = select_aliases(canonical_question, questions, max_aliases)
    return {
        "fact_id": fact_id,
        "category": category,
        "canonical_question": canonical_question,
        "answer": answer,
        "aliases": aliases,
        "source_rows": sorted(set(source_rows)),
        "priority": priority,
    }


def select_aliases(canonical_question, questions, max_aliases):
    selected = []
    seen = set()
    for question in [canonical_question, *questions]:
        question = normalize_question_text(question)
        if not question:
            continue
        key = comparable(question)
        if key in seen:
            continue
        seen.add(key)
        selected.append(question)
        if len(selected) >= max_aliases:
            break
    return selected


def flatten_facts(facts):
    import_rows = []
    audit_rows = []
    seen_import = set()
    for fact in sorted(facts, key=lambda item: (-item["priority"], item["fact_id"])):
        answer_hash = hashlib.sha1(fact["answer"].encode("utf-8")).hexdigest()[:12]
        source_range = compact_ranges(fact["source_rows"])
        for idx, question in enumerate(fact["aliases"], 1):
            key = (comparable(question), comparable(fact["answer"]))
            if key in seen_import:
                continue
            seen_import.add(key)
            import_rows.append([question, fact["answer"]])
            audit_rows.append(
                {
                    "fact_id": fact["fact_id"],
                    "category": fact["category"],
                    "priority": fact["priority"],
                    "alias_index": idx,
                    "question": question,
                    "canonical_question": fact["canonical_question"],
                    "answer": fact["answer"],
                    "answer_hash": answer_hash,
                    "source_rows": source_range,
                }
            )
    return import_rows, audit_rows


def write_import_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def write_audit_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "fact_id",
        "category",
        "priority",
        "alias_index",
        "question",
        "canonical_question",
        "answer",
        "answer_hash",
        "source_rows",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_notes(path, facts, import_rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = defaultdict(int)
    for fact in facts:
        counts[fact["category"]] += 1
    lines = [
        "# Enterprise Facts Q/A Import Notes",
        "",
        "生成目标：把 `identity.csv` 规整为企业客服快答事实卡片，减少重复问法挤占 RAG top_k。",
        "",
        "## Files",
        "",
        f"- `enterprise_facts_qa_import.csv`: RAGFlow 导入文件，两列，无表头，列顺序为问题、答案。",
        f"- `enterprise_facts_qa_audit.csv`: 审计文件，包含分类、优先级、来源行号和答案哈希。",
        "",
        "## Import Rules",
        "",
        "- 字段型问题（地址、电话、人数、地点）答案第一句必须直接给结论。",
        "- 同一事实只保留少量高质量问法，避免 20 条以上重复别名把其他事实挤出检索结果。",
        "- 企业总部地址、电话、科学家数量、临床应用中心位置做了事实合并，避免同义答案互相竞争。",
        "- 长资料仍建议保留在资料库，用于详细介绍类问题；本文件主要用于快问快答。",
        "",
        "## Summary",
        "",
        f"- facts: {len(facts)}",
        f"- import rows: {len(import_rows)}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in sorted(counts.items()):
        lines.append(f"- {category}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def infer_category(question, answer):
    text = f"{question} {answer}"
    for category, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return category
    return "general"


def default_priority(category):
    return {
        "address": 90,
        "phone": 90,
        "personnel_count": 85,
        "facility_location": 80,
        "business": 75,
        "company_intro": 70,
        "timeline": 65,
        "personnel": 60,
        "assistant_identity": 55,
        "certification": 55,
    }.get(category, 50)


def max_aliases_for_category(category):
    return {
        "address": 8,
        "phone": 8,
        "business": 6,
        "company_intro": 6,
        "timeline": 4,
        "personnel": 4,
        "assistant_identity": 5,
        "certification": 4,
    }.get(category, 4)


def choose_canonical_question(questions):
    preferred = sorted(
        (normalize_question_text(question) for _, question in questions),
        key=lambda item: (question_penalty(item), len(item)),
    )
    return preferred[0] if preferred else ""


def question_penalty(question):
    penalty = 0
    if question.startswith(("请问", "能告诉我", "可以告诉我", "能说说")):
        penalty += 2
    if "详细" in question or "具体" in question:
        penalty += 1
    if len(question) > 26:
        penalty += 1
    return penalty


def clean_answer(answer):
    text = normalize_spaces(answer)
    text = text.replace("（帮你制定饮食 / 运动计划）", "（帮你制定饮食/运动计划）")
    text = re.sub(r"\s*([#])\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    if not text.endswith(("。", "！", "？", "!", "?")):
        text += "。"
    return text


def normalize_question_text(question):
    text = normalize_spaces(question)
    text = text.rstrip("。.")
    if text and not text.endswith(("？", "?")):
        text += "？"
    return text


def normalize_spaces(text):
    text = str(text or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([，。！？；：、）】》])", r"\1", text)
    text = re.sub(r"([（【《])\s+", r"\1", text)
    return text


def comparable(text):
    text = re.sub(r"\s+", "", str(text or "")).lower()
    return text.strip("，,。.!！?？;；:：、\"'“”‘’`()（）[]【】")


def flatten_source_rows(groups):
    rows = []
    for group in groups:
        rows.extend(row for row, _ in group["questions"])
    return rows


def compact_ranges(values):
    values = sorted(set(values))
    if not values:
        return ""
    ranges = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(format_range(start, prev))
        start = prev = value
    ranges.append(format_range(start, prev))
    return ";".join(ranges)


def format_range(start, end):
    return str(start) if start == end else f"{start}-{end}"


if __name__ == "__main__":
    main()

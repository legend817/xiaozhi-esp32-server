import re


_ANSWER_MARKER = re.compile(
    r"(?:^|[\r\n\t])\s*(?:回答|答案)\s*[:：]\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_QA_CONTENT_PATTERN = re.compile(
    r"(?:^|[\r\n])\s*(?:问题|提问)\s*[:：]\s*(.*?)\s*"
    r"(?:[\r\n\t]+|\s{2,})\s*(?:回答|答案)\s*[:：]\s*(.*?)\s*"
    r"(?=$|[\r\n]+\s*(?:问题|提问)\s*[:：])",
    re.IGNORECASE | re.DOTALL,
)
_EXPLANATION_QUERY_TERMS = (
    "详细",
    "全面",
    "展开",
    "深入",
    "介绍",
    "为什么",
    "原因",
    "原理",
    "如何",
    "怎么做",
    "对比",
    "区别",
    "关系",
    "依据",
    "影响",
)
_DETAIL_QUERY_TERMS = (
    "分别",
    "具体",
    "包括",
    "有哪些",
    "哪些",
    "名单",
    "列出",
)
_COUNT_QUERY_PATTERN = re.compile(r"(?:多少|几位|几人|几个|数量|总数|一共)")
_COUNT_ANSWER_TAIL = re.compile(r"[，,；;:]\s*(?:分别|包括|具体|其中).*$", re.DOTALL)
_PHONE_SEPARATOR_SPACE = re.compile(r"(?<=\d[-－—])\s+(?=\d)")
_SENTENCE_END_PATTERN = re.compile(r"[。！？!?；;]")
_ORG_SUBJECT_PATTERN = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9·]{2,24}?(?:集团|公司|企业|总部))"
)
_FAQ_QUERY_PREFIX_PATTERN = re.compile(
    r"^(?:(?:请问|请帮我|麻烦|帮我|查询一下|查一下|查询|我想知道|"
    r"能否告诉我|可以告诉我|告诉我))+(?:一下)?"
)
_FACILITY_TERMS = (
    "中心",
    "实验室",
    "基地",
    "医院",
    "门店",
    "分部",
    "分公司",
    "办事处",
)
_LOCATION_QUERY_TERMS = (
    "地址",
    "在哪里",
    "在哪儿",
    "在哪",
    "什么地方",
    "何处",
    "什么位置",
    "哪个位置",
    "所在地",
    "办公地点",
    "办公地址",
    "坐落",
)
_NON_LOCATION_QUERY_TERMS = (
    "哪些机构",
    "哪些单位",
    "哪些企业",
    "哪些公司",
    "哪些合作",
    "在哪些",
)
_ENTITY_QUESTION_PATTERNS = (
    re.compile(
        r"^(?:请问)?([\u4e00-\u9fff·]{2,6}?)(?:是)?(?:谁|什么人|做什么的|干什么的)(?:[？?。.]*)$"
    ),
    re.compile(
        r"^(?:请|麻烦)?(?:介绍一下|介绍下|介绍)([\u4e00-\u9fff·]{2,6})(?:[？?。.]*)$"
    ),
)
_NON_ENTITY_TERMS = {
    "一下",
    "分别",
    "他们",
    "她们",
    "它们",
    "哪些",
    "人员",
    "员工",
    "团队",
    "公司",
    "集团",
    "科学家",
    "负责人",
    "创始人",
}


def select_rag_contexts(contents, max_chunks, max_chars):
    """Select compact RAG contexts while removing repeated Q&A answers.

    A Q&A knowledge base may store multiple question aliases with the same answer.
    RAGFlow can return several of those aliases for one query. Deduplicating by the
    answer portion keeps those aliases from consuming every context slot.
    """
    selected = []
    seen_keys = set()
    used_chars = 0
    duplicate_count = 0

    for raw_content in contents:
        content = str(raw_content or "").strip()
        if not content:
            continue

        dedupe_key = _context_dedupe_key(content)
        if dedupe_key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(dedupe_key)

        remaining = max_chars - used_chars
        if remaining <= 0 or len(selected) >= max_chunks:
            break
        if len(content) > remaining:
            content = content[:remaining].rstrip()
        if not content:
            break

        selected.append(content)
        used_chars += len(content)

    return selected, duplicate_count


def extract_entity_query_term(question):
    """Return the short Chinese entity in a tightly-scoped person question."""
    text = re.sub(r"\s+", "", str(question or ""))
    for pattern in _ENTITY_QUESTION_PATTERNS:
        match = pattern.match(text)
        if match:
            term = match.group(1)
            return "" if term in _NON_ENTITY_TERMS else term
    return ""


def filter_contexts_containing_term(chunks, term):
    """Keep fallback chunks that explicitly contain the requested entity."""
    if not term:
        return []
    return [chunk for chunk in chunks if term in str(chunk.get("content", ""))]


def build_enterprise_faq_cache_alias(question):
    """Return a conservative ``(category, alias)`` for reusable direct answers.

    The alias is intentionally unavailable for explanatory questions and only
    covers unambiguous enterprise FAQ fields. It is scoped again by dataset and
    retrieval configuration when the final cache key is built.
    """
    text = re.sub(r"\s+", "", str(question or "")).strip()
    text = text.strip("，,。.!！?？;；:：、\"'“”‘’`()（）[]【】")
    if not text or any(term in text for term in _EXPLANATION_QUERY_TERMS):
        return "", ""

    entity_term = extract_entity_query_term(text)
    if entity_term:
        return "person", f"person:{entity_term}"

    normalized = _FAQ_QUERY_PREFIX_PATTERN.sub("", text)
    subject = _extract_org_subject(normalized)
    if not subject:
        return "", ""

    if any(term in normalized for term in ("联系电话", "客服电话", "服务热线", "电话")):
        return "phone", f"phone:{subject}"

    if _is_location_query(normalized) and not any(term in normalized for term in _FACILITY_TERMS):
        return "org_address", f"org_address:{subject}"

    if any(
        term in normalized
        for term in ("主营业务", "主要业务", "主营什么", "经营范围", "主要做什么")
    ):
        return "main_business", f"main_business:{subject}"

    if (
        _COUNT_QUERY_PATTERN.search(normalized)
        and any(term in normalized for term in ("科学家", "专家"))
        and not _asks_for_detail(normalized)
    ):
        personnel_type = "科学家" if "科学家" in normalized else "专家"
        return "personnel_count", f"personnel_count:{subject}:{personnel_type}"

    return "", ""


def build_enterprise_faq_retrieval_question(question, category, alias):
    """Rewrite short enterprise FAQ queries into retrieval-friendly wording."""
    if not category or not alias:
        return str(question or "")

    subject = _alias_subject(alias)
    if not subject:
        return str(question or "")

    if category == "org_address":
        return f"{subject} 地址"
    if category == "phone":
        return f"{subject} 联系电话"
    if category == "main_business":
        return f"{subject} 主营业务"
    return str(question or "")


def select_direct_qa_answer(
    question,
    chunks,
    min_similarity=0.36,
    min_support=2,
    min_score_gap=0.03,
    max_chars=75,
):
    """Return a safe canonical Q&A answer or an empty string.

    Direct answers are intentionally conservative: an exact stored question may
    answer directly, otherwise at least two retrieved aliases must agree on the
    same answer and beat any competing answer by a small score margin. Questions
    asking for explanation or synthesis continue through the LLM.
    """
    query = str(question or "").strip()
    if not query or any(term in query for term in _EXPLANATION_QUERY_TERMS):
        return ""

    candidates = []
    for chunk in chunks or []:
        stored_question, answer = _parse_qa_content(chunk.get("content", ""))
        if not stored_question or not answer:
            continue
        try:
            score = float(chunk.get("similarity", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        candidates.append(
            {
                "question": stored_question,
                "answer": answer,
                "answer_key": _normalize_comparable_text(answer),
                "score": score,
            }
        )

    if not candidates:
        return ""

    normalized_query = _normalize_comparable_text(query)
    exact_matches = [
        item
        for item in candidates
        if _normalize_comparable_text(item["question"]) == normalized_query
        and item["score"] >= min_similarity
    ]
    if exact_matches:
        chosen = sorted(exact_matches, key=lambda item: (-item["score"], len(item["answer"])))[0]
        return _prepare_direct_answer(query, chosen["answer"], max_chars)

    grouped = {}
    for item in candidates:
        group = grouped.setdefault(
            item["answer_key"],
            {"answer": item["answer"], "support": 0, "max_score": 0.0},
        )
        group["support"] += 1
        group["max_score"] = max(group["max_score"], item["score"])

    ranked = sorted(
        grouped.values(),
        key=lambda item: (-item["max_score"], -item["support"], len(item["answer"])),
    )
    best = ranked[0]
    if best["support"] < min_support or best["max_score"] < min_similarity:
        return ""
    if len(ranked) > 1 and best["max_score"] - ranked[1]["max_score"] < min_score_gap:
        return ""
    return _prepare_direct_answer(query, best["answer"], max_chars)


def select_enterprise_location_answer(
    question,
    chunks,
    subject="",
    min_similarity=0.3,
    max_chars=120,
):
    """Extract a deterministic location answer from RAG chunks."""
    query = str(question or "").strip()
    if not query or _asks_for_detail(query):
        return ""

    normalized_query = re.sub(r"\s+", "", query)
    if not _is_location_query(normalized_query):
        return ""
    if any(term in normalized_query for term in _FACILITY_TERMS):
        return ""

    subject = subject or _extract_org_subject(normalized_query)
    if not subject:
        return ""

    for chunk in chunks or []:
        try:
            score = float(chunk.get("similarity", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score < min_similarity:
            continue

        _, qa_answer = _parse_qa_content(chunk.get("content", ""))
        source_text = qa_answer or str(chunk.get("content", "") or "")
        answer = _extract_location_sentence(source_text, subject, max_chars)
        if answer:
            return answer
    return ""


def _context_dedupe_key(content):
    match = _ANSWER_MARKER.search(content)
    comparable = match.group(1) if match else content
    comparable = re.sub(r"\s+", "", comparable).lower()
    return comparable.strip("，,。.!！?？;；:：、\"'“”‘’`()（）[]【】")


def _extract_org_subject(text):
    if text.startswith(("公司", "集团", "企业", "总部")):
        return text[:2]
    match = _ORG_SUBJECT_PATTERN.search(text)
    return match.group(1) if match else ""


def _alias_subject(alias):
    parts = str(alias or "").split(":")
    return parts[1] if len(parts) >= 2 and parts[1] else ""


def _parse_qa_content(content):
    text = str(content or "")
    match = _QA_CONTENT_PATTERN.search(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    # RAGFlow may flatten an imported CSV row into one line:
    # ``问题：... 回答：...``. Only explicit Q/A markers use this fallback.
    flattened = re.search(
        r"(?:问题|提问)\s*[:：]\s*(.*?)\s+(?:回答|答案)\s*[:：]\s*(.*)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not flattened:
        return "", ""
    return flattened.group(1).strip(), flattened.group(2).strip()


def _extract_location_sentence(text, subject, max_chars):
    normalized = _normalize_answer_text(text)
    if not normalized or subject not in normalized:
        return ""

    sentence = _sentence_containing_location(normalized, subject)
    if not sentence:
        return ""

    sentence = _trim_location_sentence_prefix(sentence, subject)
    sentence = sentence.strip("，,；;:：、 ")
    if not sentence:
        return ""
    if not sentence.endswith(("。", "！", "？", "!", "?")):
        sentence += "。"
    if len(sentence) > max_chars:
        return ""
    return sentence


def _sentence_containing_location(text, subject):
    for sentence in re.split(r"(?<=[。！？!?；;])", text):
        if subject not in sentence:
            continue
        compact = re.sub(r"\s+", "", sentence)
        if any(term in compact for term in ("地址", "办公地址", "总部位于", "总部坐落", "位于", "坐落于", "所在地")):
            return sentence
    compact = re.sub(r"\s+", "", text)
    if subject not in compact:
        return ""
    if any(term in compact for term in ("地址", "办公地址", "总部位于", "总部坐落", "位于", "坐落于", "所在地")):
        return text
    return ""


def _trim_location_sentence_prefix(sentence, subject):
    candidates = []
    for marker in (
        f"{subject}的地址",
        f"{subject}地址",
        f"{subject}总部位于",
        f"{subject}总部坐落",
        f"{subject}位于",
        f"{subject}坐落于",
    ):
        index = sentence.find(marker)
        if index >= 0:
            candidates.append(index)
    if candidates:
        sentence = sentence[min(candidates):]

    hard_end = _SENTENCE_END_PATTERN.search(sentence)
    if hard_end:
        return sentence[: hard_end.start() + 1]
    return sentence


def _normalize_comparable_text(text):
    normalized = re.sub(r"\s+", "", str(text or "")).lower()
    return normalized.strip("，,。.!！?？;；:：、\"'“”‘’`()（）[]【】")


def _prepare_direct_answer(question, answer, max_chars):
    text = _normalize_answer_text(answer)
    if _is_location_question(question) and not _asks_for_detail(question):
        location_text = _first_sentence(text)
        if location_text:
            text = location_text
    if _COUNT_QUERY_PATTERN.search(str(question or "")) and not _asks_for_detail(question):
        compact = _COUNT_ANSWER_TAIL.sub("", text).rstrip("，,；;:：。.")
        if compact:
            text = compact + "。"
    if not text or len(text) > max_chars:
        return ""
    return text


def _is_location_question(text):
    normalized = re.sub(r"\s+", "", str(text or ""))
    return _is_location_query(normalized)


def _is_location_query(normalized):
    return any(term in normalized for term in _LOCATION_QUERY_TERMS) and not any(
        term in normalized for term in _NON_LOCATION_QUERY_TERMS
    )


def _first_sentence(text):
    normalized = _normalize_answer_text(text)
    if not normalized:
        return ""
    match = _SENTENCE_END_PATTERN.search(normalized)
    if match:
        return normalized[: match.start() + 1].strip()
    split = re.split(r"(?:其中|同时|另外|此外|并且)", normalized, maxsplit=1)
    return split[0].rstrip("，,；;:：。.") + "。" if split and split[0].strip() else normalized


def _asks_for_detail(text):
    normalized = re.sub(r"\s+", "", str(text or ""))
    return any(term in normalized for term in _DETAIL_QUERY_TERMS)


def _normalize_answer_text(text):
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    normalized = _PHONE_SEPARATOR_SPACE.sub("", normalized)
    return normalized

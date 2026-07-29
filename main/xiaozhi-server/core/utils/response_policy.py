import re
from dataclasses import dataclass
from typing import Optional


_PUNCTUATION_PATTERN = re.compile(r"[，。！？；：、,.!?;:\s]+")
_FORBIDDEN_FOLLOWUPS = (
    "要继续听吗",
    "还要继续听吗",
    "要不要继续听",
    "要我继续介绍吗",
    "要我继续说明吗",
    "需要我继续介绍吗",
    "需要我继续说明吗",
)


@dataclass
class ResponsePolicy:
    name: str
    max_chars: int
    instruction: str
    suffix: str = ""
    close_on_sentence_end: bool = False
    topic_guard: str = (
        "本轮必须优先回答当前用户问题；上一轮对话只作语气参考，"
        "不得延续上一轮业务场景。若当前问题与上一轮无关，必须立即切换主题。"
    )


class ResponseBudget:
    """Streaming-safe response budget gate.

    It limits the text sent to TTS while the LLM stream is still being consumed.
    The dialogue history should store only the text returned by `accept`, because
    that is what the user actually heard.
    """

    def __init__(self, policy: ResponsePolicy):
        self.policy = policy
        self.sent_chars = 0
        self.closed = False
        self.suffix_sent = False
        self.truncated = False
        self.last_sent_char = ""
        self._followup_pending = ""
        self._followup_blocked = False

    def accept(self, text: Optional[str]) -> str:
        if not text or self.closed:
            return ""

        text = self._filter_forbidden_followup(text)
        if not text:
            return ""

        return self._accept_budget(text)

    def finish(self) -> str:
        """Flush a legitimate partial suffix after the LLM stream ends."""
        if self.closed or self._followup_blocked or not self._followup_pending:
            return ""
        pending = self._followup_pending
        self._followup_pending = ""
        return self._accept_budget(pending)

    def _accept_budget(self, text: str) -> str:

        if self.policy.close_on_sentence_end:
            sentence_end = self._find_sentence_end(text)
            if sentence_end >= 0:
                text = text[: sentence_end + 1]
                self.closed = True

        remaining = self.policy.max_chars - self.sent_chars
        if remaining <= 0:
            return self._close_with_suffix()

        if len(text) <= remaining:
            self.sent_chars += len(text)
            self.last_sent_char = text[-1]
            return text

        self.truncated = True
        clipped = self._clip_at_sentence_boundary(text[:remaining])
        self.sent_chars += len(clipped)
        if clipped:
            self.last_sent_char = clipped[-1]
        return clipped + self._close_with_suffix()

    def _filter_forbidden_followup(self, text: str) -> str:
        if self._followup_blocked:
            return ""

        combined = self._followup_pending + text
        self._followup_pending = ""
        matches = [
            (combined.find(phrase), phrase)
            for phrase in _FORBIDDEN_FOLLOWUPS
            if phrase in combined
        ]
        if matches:
            position, _ = min(matches, key=lambda item: item[0])
            self._followup_blocked = True
            return combined[:position].rstrip()

        hold_length = 0
        for phrase in _FORBIDDEN_FOLLOWUPS:
            max_prefix = min(len(phrase) - 1, len(combined))
            for prefix_length in range(max_prefix, 0, -1):
                if combined.endswith(phrase[:prefix_length]):
                    hold_length = max(hold_length, prefix_length)
                    break
        if hold_length:
            self._followup_pending = combined[-hold_length:]
            return combined[:-hold_length]
        return combined

    def _find_sentence_end(self, text: str) -> int:
        positions = [text.find(p) for p in "。！？!?"]
        positions = [pos for pos in positions if pos >= 0]
        if not positions:
            return -1
        end = min(positions)
        while end + 1 < len(text) and text[end + 1] in "”」』'\"":
            end += 1
        return end

    def _clip_at_sentence_boundary(self, text: str) -> str:
        # Avoid sending a fragment after the last natural punctuation when possible.
        if len(text) <= 12:
            return text
        boundary = max(text.rfind(p) for p in "。！？；，,.!?;")
        if boundary >= 8:
            return text[: boundary + 1]
        return text

    def _close_with_suffix(self) -> str:
        if self.closed:
            return ""
        self.closed = True
        suffix = self.policy.suffix
        if suffix and not self.suffix_sent:
            self.suffix_sent = True
            return suffix
        if self.truncated and not self.suffix_sent:
            self.suffix_sent = True
            if self.last_sent_char not in "。！？!?":
                return "。"
        return ""


class StreamingTextSegmenter:
    """Buffer streamed text and emit TTS-sized segments at natural punctuation."""

    def __init__(
        self,
        soft_min_chars: int = 28,
        max_segment_chars: int = 90,
        first_segment_max_chars: int = 28,
    ):
        self.soft_min_chars = max(1, soft_min_chars)
        self.max_segment_chars = max(self.soft_min_chars, max_segment_chars)
        self.first_segment_max_chars = max(1, min(first_segment_max_chars, self.max_segment_chars))
        self.buffer = ""
        self.emitted_segments = 0
        self.major_punctuations = "。！？!?；;\n"
        self.soft_punctuations = "，,、：:"

    def accept(self, text: Optional[str]) -> list[str]:
        if not text:
            return []
        self.buffer += text
        return self._drain(flush=False)

    def flush(self) -> list[str]:
        return self._drain(flush=True)

    def _drain(self, flush: bool) -> list[str]:
        segments = []
        while self.buffer:
            cut = self._find_cut(flush)
            if cut <= 0:
                break
            segment = self.buffer[:cut].strip()
            self.buffer = self.buffer[cut:]
            if segment:
                segments.append(segment)
                self.emitted_segments += 1
        return segments

    def _find_cut(self, flush: bool) -> int:
        max_chars = (
            self.first_segment_max_chars
            if self.emitted_segments == 0
            else self.max_segment_chars
        )
        major = self._first_punctuation(self.buffer, self.major_punctuations)
        if 0 <= major < max_chars:
            return major + 1
        if self.emitted_segments == 0 and len(self.buffer) >= max_chars:
            return max_chars

        soft = self._last_punctuation_before(
            self.buffer,
            self.soft_punctuations,
            max_chars,
        )
        if soft >= self.soft_min_chars:
            return soft + 1

        if len(self.buffer) >= max_chars:
            return max_chars
        if flush:
            return len(self.buffer)
        return 0

    @staticmethod
    def _first_punctuation(text: str, punctuations: str) -> int:
        positions = [text.find(p) for p in punctuations]
        positions = [pos for pos in positions if pos >= 0]
        return min(positions) if positions else -1

    @staticmethod
    def _last_punctuation_before(text: str, punctuations: str, limit: int) -> int:
        window = text[:limit]
        return max(window.rfind(p) for p in punctuations)


def build_response_policy(
    query: Optional[str], route_name: Optional[str] = None
) -> ResponsePolicy:
    text = _normalize(query)
    enterprise_route = route_name in {"enterprise_rag", "enterprise_rag_probe"}
    explanation_requested = _contains_any(
        text,
        (
            "详细",
            "全面",
            "展开",
            "深入",
            "为什么",
            "如何",
            "怎么做",
            "解释",
            "介绍",
            "对比",
            "区别",
            "原理",
        ),
    )

    if _contains_any(text, ("笑话", "冷笑话", "段子", "逗我笑")):
        return ResponsePolicy(
            name="joke",
            max_chars=40,
            instruction=(
                "本轮回复是短笑话模式：只讲一个完整短笑话，不超过40个汉字；"
                "不要铺垫，不解释笑点，不追加“要继续听吗”。"
            ),
            close_on_sentence_end=True,
        )

    if enterprise_route and explanation_requested:
        return ResponsePolicy(
            name="enterprise_explain",
            max_chars=420,
            instruction=(
                "本轮回复是企业知识解释模式：基于知识库先给结论，再按自然句补充关键事实；"
                "第一句必须是30个汉字以内的完整结论句，并以句号、问号或感叹号结束，便于立即播报；"
                "可以输出较完整内容，但每句话必须句意完整，避免一口气堆成长段；"
                "不要开始无法在预算内说明完整的新日期、名单或案例；不确定时不要编造；"
                "不要主动追加“要继续听吗”“要我继续介绍吗”等续问。"
            ),
        )

    if enterprise_route or _contains_any(
        text,
        (
            "客服",
            "公司",
            "企业",
            "集团",
            "产品",
            "服务",
            "业务",
            "价格",
            "报价",
            "收费",
            "套餐",
            "方案",
            "合作",
            "官网",
            "联系",
            "联系方式",
            "电话",
            "地址",
            "营业时间",
            "售前",
            "资质",
            "案例",
            "客户",
            "发票",
            "合同",
            "临床",
            "科学家",
        ),
    ):
        return ResponsePolicy(
            name="enterprise_qa",
            max_chars=260,
            instruction=(
                "本轮回复是企业客服/企业信息问答模式：先直接回答用户问到的企业信息；"
                "第一句必须是30个汉字以内的完整结论句，并以句号、问号或感叹号结束，便于立即播报；"
                "只回答用户所问字段，不无关扩展；需要列举时按自然句分批输出，不要堆成长段；"
                "不确定时说明需要查询资料，不要编造；"
                "不要主动追加“要继续听吗”“要我继续介绍吗”等续问。"
            ),
        )

    if _contains_any(
        text,
        (
            "为什么",
            "怎么",
            "如何",
            "解释",
            "介绍",
            "方案",
            "计划",
            "步骤",
            "原理",
            "知识库",
            "文档",
        ),
    ):
        return ResponsePolicy(
            name="explain",
            max_chars=90,
            instruction=(
                "本轮回复是解释模式：先给结论，再给最多2个关键点；"
                "不超过90个汉字；不要主动追加“要继续听吗”“要我继续说明吗”等续问。"
            ),
        )

    return ResponsePolicy(
        name="fast_default",
        max_chars=60,
        instruction=(
            "本轮回复是极速模式：先直接回答核心问题，不超过60个汉字；"
            "不要铺垫，不主动扩展背景。"
        ),
    )


def _normalize(text: Optional[str]) -> str:
    return _PUNCTUATION_PATTERN.sub("", text or "").lower()


def _contains_any(text: str, keywords) -> bool:
    return any(keyword.lower() in text for keyword in keywords)

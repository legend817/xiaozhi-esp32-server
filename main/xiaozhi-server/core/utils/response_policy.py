import re
from dataclasses import dataclass
from typing import Optional


_PUNCTUATION_PATTERN = re.compile(r"[，。！？；：、,.!?;:\s]+")


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

    def accept(self, text: Optional[str]) -> str:
        if not text or self.closed:
            return ""

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
            return text

        self.truncated = True
        clipped = self._clip_at_sentence_boundary(text[:remaining])
        self.sent_chars += len(clipped)
        return clipped + self._close_with_suffix()

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
        return ""


def build_response_policy(query: Optional[str]) -> ResponsePolicy:
    text = _normalize(query)

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

    if _contains_any(
        text,
        (
            "客服",
            "公司",
            "企业",
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
        ),
    ):
        return ResponsePolicy(
            name="enterprise_qa",
            max_chars=75,
            suffix="要我继续介绍哪一项？",
            instruction=(
                "本轮回复是企业客服/企业信息问答模式：先直接回答用户问到的企业信息；"
                "不超过75个汉字，不一次列超过2点；不确定时说明需要查询资料，不要编造。"
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
            suffix="要我继续说明吗？",
            instruction=(
                "本轮回复是解释模式：先给结论，再给最多2个关键点；"
                "不超过90个汉字，需要更多细节时问是否继续。"
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

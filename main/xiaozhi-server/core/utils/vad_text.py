import re


_ASR_TAG_PATTERN = re.compile(r"<\|[^|]+\|>")
_INCOMPLETE_COMMAND_FRAGMENT = re.compile(
    r"^(?:(?:请|麻烦)?介绍(?:一(?:下)?|下)?|"
    r"(?:请|麻烦)?(?:帮我)?查(?:一(?:下)?|下)?|"
    r"我想(?:问|了解)(?:一(?:下)?|下)?|"
    r"(?:请|麻烦)?问(?:一(?:下)?|下)?)$"
)
_INCOMPLETE_COMMAND_ENDINGS = (
    "请介绍一下",
    "介绍一下",
    "请介绍",
    "帮我查一下",
    "帮我查",
    "查一下",
    "查询一下",
    "我想问一下",
    "我想问",
    "我想了解一下",
    "我想了解",
    "请问一下",
    "请问",
    "麻烦介绍一下",
    "麻烦查一下",
    "你能介绍一下",
    "能不能介绍一下",
    "可以介绍一下",
)
_INCOMPLETE_CONNECTOR_ENDINGS = (
    "关于",
    "有关",
    "以及",
    "还有",
    "或者",
    "然后",
    "比如",
    "例如",
    "的",
    "和",
    "与",
)


def is_incomplete_asr_partial(text):
    """Return whether an online ASR partial clearly expects more speech."""
    normalized = _ASR_TAG_PATTERN.sub("", str(text or ""))
    normalized = re.sub(r"[\s，,。.!！?？;；:：、\"'“”‘’`()（）]+", "", normalized)
    if not normalized:
        return False
    if _INCOMPLETE_COMMAND_FRAGMENT.match(normalized):
        return True
    return normalized.endswith(
        _INCOMPLETE_COMMAND_ENDINGS + _INCOMPLETE_CONNECTOR_ENDINGS
    )

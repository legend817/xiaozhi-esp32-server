from dataclasses import dataclass
import re
from typing import Iterable, List, Optional, Set

from core.utils.rag_context import extract_entity_query_term


@dataclass(frozen=True)
class ToolRoute:
    name: str
    tool_names: List[str]
    reason: str

    @property
    def enabled(self) -> bool:
        return bool(self.tool_names)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _available_prefixed(available_tools: Set[str], prefixes: Iterable[str]) -> List[str]:
    result = []
    for tool_name in sorted(available_tools):
        if any(tool_name.startswith(prefix) for prefix in prefixes):
            result.append(tool_name)
    return result


def _enterprise_subject_hints(description: Optional[str]) -> List[str]:
    """Extract stable organization names from the configured RAG description."""

    if not description:
        return []
    names = re.findall(r"【([^】]+)】", description)
    hints = []
    removable_suffixes = (
        "知识库",
        "公司信息",
        "企业信息",
        "集团信息",
        "信息",
        "资料",
        "介绍",
        "公司",
        "企业",
        "集团",
    )
    for name_group in names:
        for raw_name in re.split(r"[,，、]", name_group):
            name = re.sub(r"[_-](?:qa|v)[\w.-]*$", "", raw_name.strip().lower())
            changed = True
            while changed and name:
                changed = False
                for suffix in removable_suffixes:
                    if name.endswith(suffix) and len(name) > len(suffix) + 1:
                        name = name[: -len(suffix)]
                        changed = True
                        break
            if len(name) >= 2 and name not in hints:
                hints.append(name)
    return hints


def build_tool_route(
    query: Optional[str],
    available_tool_names: Iterable[str],
    enterprise_rag_description: Optional[str] = None,
) -> ToolRoute:
    """Select the smallest useful tool set for the current user query.

    This is intentionally deterministic and conservative:
    - direct chat stays tools=false;
    - only clearly matched capabilities receive tools;
    - if the configured tool is unavailable, the route falls back to direct LLM.
    """

    text = (query or "").strip().lower()
    available = set(available_tool_names or [])
    if not text or not available:
        return ToolRoute("direct_llm", [], "empty_query_or_no_tools")

    def pick(route_name: str, candidates: List[str], reason: str) -> ToolRoute:
        selected = [name for name in candidates if name in available]
        if not selected:
            return ToolRoute("direct_llm", [], f"{route_name}_tool_unavailable")
        return ToolRoute(route_name, selected, reason)

    # 退出/待机类：强确定性，优先级最高。
    if _contains_any(text, ["再见", "拜拜", "退出", "结束对话", "别说了", "退下", "待机", "晚安"]):
        return pick("exit", ["handle_exit_intent"], "matched_exit_keywords")

    # 设备端 MCP / IoT 控制：音量、亮度、主题、状态等。
    if _contains_any(text, ["音量", "声音大", "声音小", "调大声", "调小声", "静音"]):
        return pick(
            "device_volume",
            ["self_get_device_status", "self_audio_speaker_set_volume", "hass_get_state", "hass_set_state"],
            "matched_device_volume_keywords",
        )
    if _contains_any(text, ["亮度", "屏幕亮", "屏幕暗"]):
        return pick(
            "device_brightness",
            ["self_get_device_status", "self_screen_set_brightness", "hass_get_state", "hass_set_state"],
            "matched_device_brightness_keywords",
        )
    if _contains_any(text, ["主题", "深色", "浅色", "暗色", "亮色"]):
        return pick(
            "device_theme",
            ["self_get_device_status", "self_screen_set_theme"],
            "matched_device_theme_keywords",
        )
    if _contains_any(text, ["电量", "网络", "设备状态", "当前状态"]):
        selected = _available_prefixed(available, ["self_get_device_status", "device_", "iot_"])
        if "hass_get_state" in available:
            selected.append("hass_get_state")
        if selected:
            return ToolRoute("device_status", selected, "matched_device_status_keywords")

    # 音乐类。
    if _contains_any(text, ["播放", "放一首", "听歌", "音乐", "歌曲", "有声书"]):
        return pick("music", ["play_music", "hass_play_music"], "matched_music_keywords")

    # 天气类。
    if _contains_any(text, ["天气", "气温", "温度", "下雨", "降雨", "空气质量", "刮风", "台风"]):
        return pick("weather", ["get_weather"], "matched_weather_keywords")

    # 时间/农历/节气类。
    if _contains_any(text, ["农历", "阴历", "节气", "生肖", "星座", "天干地支", "宜忌", "黄历"]):
        return pick("time_lunar", ["get_lunar"], "matched_lunar_keywords")

    # 新闻类。
    if _contains_any(text, ["新闻", "热搜", "头条", "资讯", "今天发生", "最近发生"]):
        return pick(
            "news",
            ["get_news_from_newsnow", "get_news_from_chinanews"],
            "matched_news_keywords",
        )

    # 企业知识库类。当前只在 search_from_ragflow 已启用时触发。
    enterprise_subject_keywords = ["公司", "企业", "你们", "我们", "集团"]
    configured_subject_hints = _enterprise_subject_hints(enterprise_rag_description)
    if configured_subject_hints and _contains_any(text, configured_subject_hints):
        return pick(
            "enterprise_rag",
            ["search_from_ragflow"],
            "matched_configured_enterprise_subject",
        )

    enterprise_contact_keywords = [
        "电话",
        "手机号",
        "手机号码",
        "联系方式",
        "联系电话",
        "联系你们",
        "怎么联系",
        "地址",
        "官网",
    ]
    if _contains_any(text, enterprise_subject_keywords) and _contains_any(
        text, enterprise_contact_keywords
    ):
        return pick(
            "enterprise_rag",
            ["search_from_ragflow"],
            "matched_enterprise_contact_keywords",
        )

    enterprise_information_keywords = [
        "做什么",
        "主营",
        "业务",
        "成立",
        "注册",
        "发展",
        "目标",
        "团队",
        "人员",
        "负责人",
        "创始人",
        "法人",
        "法定代表人",
        "ceo",
        "科学家",
        "教授",
        "博士",
        "临床",
        "试点",
        "中心",
        "实验室",
        "检测",
        "认证",
        "营业时间",
    ]
    if _contains_any(text, enterprise_subject_keywords) and _contains_any(
        text, enterprise_information_keywords
    ):
        return pick(
            "enterprise_rag",
            ["search_from_ragflow"],
            "matched_enterprise_information_keywords",
        )

    enterprise_keywords = [
        "你们公司",
        "公司是做什么",
        "公司介绍",
        "企业介绍",
        "产品",
        "价格",
        "报价",
        "方案",
        "服务",
        "联系方式",
        "联系电话",
        "联系你们",
        "公司电话",
        "企业电话",
        "合作",
        "资质",
        "案例",
        "客户",
        "官网",
        "地址",
    ]
    if _contains_any(text, enterprise_keywords):
        return pick("enterprise_rag", ["search_from_ragflow"], "matched_enterprise_keywords")

    # 人名类企业资料无法仅靠企业名称命中。仅当知识库描述明确包含
    # 人员/团队资料时做一次低风险探测；无召回时由连接层回退普通 LLM。
    description_text = (enterprise_rag_description or "").lower()
    if extract_entity_query_term(text) and _contains_any(
        description_text, ["人员", "团队", "员工", "专家", "科学家"]
    ):
        return pick(
            "enterprise_rag_probe",
            ["search_from_ragflow"],
            "matched_enterprise_entity_probe",
        )

    # 明确要求联网搜索时才启用搜索。
    if _contains_any(text, ["搜索", "查一下", "网上", "联网", "最新", "资料"]):
        return pick("web_search", ["web_search"], "matched_web_search_keywords")

    return ToolRoute("direct_llm", [], "no_rule_matched")

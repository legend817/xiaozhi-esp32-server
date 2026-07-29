from dataclasses import dataclass
from typing import Iterable, List, Optional, Set


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


def build_tool_route(query: Optional[str], available_tool_names: Iterable[str]) -> ToolRoute:
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
        "联系你们",
        "合作",
        "资质",
        "案例",
        "客户",
        "官网",
        "地址",
    ]
    if _contains_any(text, enterprise_keywords):
        return pick("enterprise_rag", ["search_from_ragflow"], "matched_enterprise_keywords")

    # 明确要求联网搜索时才启用搜索。
    if _contains_any(text, ["搜索", "查一下", "网上", "联网", "最新", "资料"]):
        return pick("web_search", ["web_search"], "matched_web_search_keywords")

    return ToolRoute("direct_llm", [], "no_rule_matched")

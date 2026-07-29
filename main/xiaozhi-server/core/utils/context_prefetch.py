"""Pure configuration guards for optional prompt-context prefetches."""


def is_weather_context_configured(config):
    """Only prefetch weather when the current agent explicitly configured it."""
    weather_config = (config or {}).get("plugins", {}).get("get_weather")
    if not isinstance(weather_config, dict):
        return False
    api_key = str(weather_config.get("api_key", "")).strip()
    api_host = str(weather_config.get("api_host", "")).strip()
    if not api_key or not api_host:
        return False
    invalid_markers = ("你的", "请填写", "placeholder")
    return not any(marker in api_key.lower() for marker in invalid_markers)

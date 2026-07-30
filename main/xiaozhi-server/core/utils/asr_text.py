import json


def build_hotwords_message(raw_hotwords):
    if not raw_hotwords:
        return "", 0

    if isinstance(raw_hotwords, dict):
        items = []
        for word, weight in raw_hotwords.items():
            word = str(word).strip()
            if not word:
                continue
            try:
                weight = int(weight)
            except (TypeError, ValueError):
                weight = 20
            items.append(f"{word} {weight}")
        return (
            json.dumps(items, ensure_ascii=False) if items else "",
            len(items),
        )

    if isinstance(raw_hotwords, list):
        normalized = {}
        for item in raw_hotwords:
            if isinstance(item, dict):
                nested_message, _ = build_hotwords_message(item)
                if nested_message:
                    normalized.update(json.loads(nested_message))
                continue
            parts = str(item).strip().rsplit(" ", 1)
            if not parts[0]:
                continue
            try:
                normalized[parts[0]] = int(parts[1]) if len(parts) == 2 else 20
            except (TypeError, ValueError):
                normalized[str(item).strip()] = 20
        return (
            json.dumps(normalized, ensure_ascii=False) if normalized else "",
            len(normalized),
        )

    text = str(raw_hotwords).strip()
    if not text:
        return "", 0
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return build_hotwords_message(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    return text, 1


def build_text_corrections(raw_corrections):
    if not raw_corrections:
        return {}
    if isinstance(raw_corrections, dict):
        return {
            str(wrong).strip(): str(correct).strip()
            for wrong, correct in raw_corrections.items()
            if str(wrong).strip() and str(correct).strip()
        }
    if isinstance(raw_corrections, list):
        result = {}
        for item in raw_corrections:
            parts = str(item).split("|", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                result[parts[0].strip()] = parts[1].strip()
        return result
    return {}


def apply_text_corrections(text, corrections):
    corrected = str(text or "")
    for wrong in sorted(corrections, key=len, reverse=True):
        corrected = corrected.replace(wrong, corrections[wrong])
    return corrected

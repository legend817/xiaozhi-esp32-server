import time
import uuid


class LatencyTracker:
    """Small per-turn latency tracker for voice pipeline measurements."""

    def __init__(self, session_id, sentence_id, query=None, depth=0):
        self.trace_id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.sentence_id = sentence_id
        self.query = query or ""
        self.depth = depth
        self.started_at = time.monotonic()
        self.marks = {}
        self.counters = {}

    @staticmethod
    def now():
        return time.monotonic()

    @staticmethod
    def ms_since(start):
        return int((time.monotonic() - start) * 1000)

    def mark(self, name):
        self.marks[name] = time.monotonic()

    def mark_once(self, name):
        if name not in self.marks:
            self.mark(name)
            return True
        return False

    def elapsed_ms(self, name=None):
        start = self.started_at if name is None else self.marks.get(name)
        if start is None:
            return None
        return int((time.monotonic() - start) * 1000)

    def since_ms(self, start_name, end_name=None):
        start = self.marks.get(start_name)
        end = self.marks.get(end_name) if end_name else time.monotonic()
        if start is None or end is None:
            return None
        return int((end - start) * 1000)

    def add_counter(self, name, value):
        self.counters[name] = self.counters.get(name, 0) + value

    def set_value(self, name, value):
        self.counters[name] = value

    def summary(self):
        fields = {
            "trace": self.trace_id,
            "depth": self.depth,
            "total_ms": self.elapsed_ms(),
            "llm_first_token_ms": self.since_ms("llm_start", "llm_first_token"),
            "llm_total_ms": self.since_ms("llm_start", "llm_end"),
            "tool_total_ms": self.counters.get("tool_total_ms"),
            "tool_count": self.counters.get("tool_count"),
            "tts_first_audio_ms": self.since_ms("chat_start", "tts_first_audio"),
            "tts_audio_total_ms": self.since_ms("tts_first_audio", "tts_end"),
            "tts_first_segment_ms": self.since_ms("chat_start", "tts_first_segment"),
            "tts_first_segment_chars": self.counters.get("tts_first_segment_chars"),
            "tts_segments": self.counters.get("tts_segments"),
            "tts_chars": self.counters.get("tts_chars"),
        }
        return " ".join(
            f"{key}={value}" for key, value in fields.items() if value is not None
        )

import json
import unittest

from core.utils.asr_text import (
    apply_text_corrections,
    build_hotwords_message,
    build_text_corrections,
)


class FunASR2PassConfigTests(unittest.TestCase):
    def test_serializes_hotword_dictionary_for_websocket_protocol(self):
        message, count = build_hotwords_message(
            {"林晓锋": 30, "中科生创": 20}
        )

        self.assertEqual(2, count)
        self.assertEqual(
            ["林晓锋 30", "中科生创 20"],
            json.loads(message),
        )

    def test_applies_configured_final_text_corrections(self):
        corrections = build_text_corrections({"林晓峰": "林晓锋"})

        self.assertEqual(
            "林晓锋是谁。",
            apply_text_corrections("林晓峰是谁。", corrections),
        )


if __name__ == "__main__":
    unittest.main()

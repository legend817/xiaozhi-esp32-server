import json
import unittest

from core.utils.asr_text import (
    apply_text_corrections,
    build_hotwords_message,
    build_text_corrections,
    normalize_chunk_size,
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


class FunASR2PassChunkSizeTests(unittest.TestCase):
    def test_normalizes_comma_separated_string(self):
        self.assertEqual(
            [5, 10, 5],
            normalize_chunk_size("5,10,5"),
        )

    def test_normalizes_bracket_string(self):
        self.assertEqual(
            [5, 10, 5],
            normalize_chunk_size("[5,10,5]"),
        )

    def test_normalizes_integer_list(self):
        self.assertEqual(
            [5, 10, 5],
            normalize_chunk_size([5, 10, 5]),
        )

    def test_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            normalize_chunk_size("abc")


if __name__ == "__main__":
    unittest.main()

import unittest

from core.utils.vad_text import is_incomplete_asr_partial


class VadPartialGuardTests(unittest.TestCase):
    def test_detects_incomplete_command_prefixes(self):
        for text in (
            "请介绍一下",
            "请介绍一",
            "请介绍下",
            "我想了解一下",
            "帮我查一下",
            "帮我查一",
            "请问",
            "中科生创的",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_incomplete_asr_partial(text))

    def test_keeps_complete_short_questions_fast(self):
        for text in (
            "查一下公司电话",
            "中科生创有多少位科学家",
            "林晓锋是谁",
            "介绍一下中科生创集团",
            "中科生创集团的临床应用中心在哪里",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_incomplete_asr_partial(text))

    def test_removes_sensevoice_tags(self):
        self.assertTrue(
            is_incomplete_asr_partial("<|zh|><|NEUTRAL|><|Speech|>请介绍一下")
        )


if __name__ == "__main__":
    unittest.main()

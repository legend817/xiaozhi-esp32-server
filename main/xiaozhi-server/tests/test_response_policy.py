import unittest

from core.utils.response_policy import (
    ResponseBudget,
    ResponsePolicy,
    StreamingTextSegmenter,
    build_response_policy,
)


class ResponseBudgetTests(unittest.TestCase):
    def test_blocks_streamed_followup_question(self):
        budget = ResponseBudget(ResponsePolicy("test", 80, ""))

        output = [
            budget.accept("联系电话是0591-87699999。"),
            budget.accept("要"),
            budget.accept("继续听吗？"),
            budget.finish(),
        ]

        self.assertEqual("联系电话是0591-87699999。", "".join(output))

    def test_flushes_legitimate_partial_prefix(self):
        budget = ResponseBudget(ResponsePolicy("test", 80, ""))

        output = budget.accept("主要要") + budget.accept("求如下。") + budget.finish()

        self.assertEqual("主要要求如下。", output)

    def test_hard_truncation_ends_with_punctuation(self):
        budget = ResponseBudget(ResponsePolicy("test", 5, ""))

        output = budget.accept("这是一个很长的回答")

        self.assertEqual("这是一个很。", output)

    def test_enterprise_route_overrides_generic_query_classification(self):
        policy = build_response_policy(
            "中科生创集团的临床应用中心在哪里？", "enterprise_rag"
        )

        self.assertEqual("enterprise_qa", policy.name)
        self.assertEqual(260, policy.max_chars)

    def test_enterprise_explanation_gets_complete_answer_budget(self):
        policy = build_response_policy(
            "请详细介绍中科生创集团的临床应用中心。", "enterprise_rag"
        )

        self.assertEqual("enterprise_explain", policy.name)
        self.assertEqual(420, policy.max_chars)

    def test_streaming_text_segmenter_emits_on_punctuation(self):
        segmenter = StreamingTextSegmenter(
            soft_min_chars=8,
            max_segment_chars=30,
            first_segment_max_chars=30,
        )

        output = []
        output += segmenter.accept("中科生创集团是生物科技企业，")
        output += segmenter.accept("聚焦医疗器械。总部位于福州")
        output += segmenter.flush()

        self.assertEqual(
            [
                "中科生创集团是生物科技企业，",
                "聚焦医疗器械。",
                "总部位于福州",
            ],
            output,
        )

    def test_streaming_text_segmenter_uses_length_fallback_without_punctuation(self):
        segmenter = StreamingTextSegmenter(
            soft_min_chars=8,
            max_segment_chars=10,
            first_segment_max_chars=10,
        )

        output = segmenter.accept("abcdefghijk")

        self.assertEqual(["abcdefghij"], output)
        self.assertEqual(["k"], segmenter.flush())

    def test_streaming_text_segmenter_prioritizes_short_first_segment(self):
        segmenter = StreamingTextSegmenter(
            soft_min_chars=8,
            max_segment_chars=90,
            first_segment_max_chars=12,
        )

        output = segmenter.accept("第一段需要尽快送入语音合成服务，后面再继续补充。")

        self.assertEqual("第一段需要尽快送入语音合", output[0])
        self.assertEqual("成服务，后面再继续补充。", output[1])

    def test_streaming_text_segmenter_default_first_segment_is_stable(self):
        segmenter = StreamingTextSegmenter()

        output = segmenter.accept("中科生创集团的临床应用中心是国家区域试点。")

        self.assertEqual("中科生创集团的临床应用中心是国家区域试点。", output[0])


if __name__ == "__main__":
    unittest.main()

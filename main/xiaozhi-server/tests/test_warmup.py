import unittest

from core.utils.cache.warmup import (
    _normalize,
    _parse_qa,
    _normalize_ids,
    _strip_prefix,
    match_warmup,
)


class WarmupNormalizeTests(unittest.TestCase):
    def test_strips_whitespace_and_punctuation(self):
        self.assertEqual("你好", _normalize("你好。"))
        self.assertEqual("你好", _normalize("  你好  ？"))
        self.assertEqual("hello", _normalize("Hello! "))

    def test_empty_returns_empty(self):
        self.assertEqual("", _normalize(""))
        self.assertEqual("", _normalize("  "))

    def test_removes_brackets_and_quotes(self):
        self.assertEqual("你好", _normalize('"你好"'))
        self.assertEqual("你好", _normalize("（你好）"))


class WarmupParseQATests(unittest.TestCase):
    def test_parse_qa_with_tab_separator(self):
        content = "问题：中科生创集团何时成立并注册？\t回答：中科生创集团（福建）有限公司成立于2021年。"
        q, a = _parse_qa(content)
        self.assertEqual("中科生创集团何时成立并注册？", q)
        self.assertEqual("中科生创集团（福建）有限公司成立于2021年。", a)

    def test_parse_qa_with_space_separator(self):
        content = "问题：公司电话是多少？ 回答：联系电话是0591-87699999。"
        q, a = _parse_qa(content)
        self.assertEqual("公司电话是多少？", q)
        self.assertEqual("联系电话是0591-87699999。", a)

    def test_parse_qa_not_qa_format(self):
        q, a = _parse_qa("这是一段纯文本")
        self.assertEqual("", q)
        self.assertEqual("", a)

    def test_parse_qa_empty_string(self):
        q, a = _parse_qa("")
        self.assertEqual("", q)
        self.assertEqual("", a)


class WarmupMatchTests(unittest.TestCase):
    def setUp(self):
        # Pre-populate Redis with test Q&A pairs
        from core.utils.cache.redis_client import redis_client
        from core.utils.cache.warmup import _cache_qa

        # Clear old test data
        redis_client.delete("cache:warmup:test_company_founded")
        redis_client.delete("cache:warmup:alias:phone:测试公司")
        redis_client.delete("cache:warmup:cat:phone")

        # Populate test data
        _cache_qa("测试公司何时成立", "测试公司成立于2020年。")
        _cache_qa("测试公司电话是多少", "测试公司电话是400-123-4567。")

    def test_exact_match_returns_answer(self):
        result = match_warmup("测试公司何时成立")
        self.assertEqual("测试公司成立于2020年。", result)

    def test_fuzzy_match_by_category(self):
        # "查一下公司的电话" should match via phone alias → cat:phone fallback
        result = match_warmup("查一下公司的电话")
        self.assertIsNotNone(result)
        self.assertIn("电话", result)

    def test_no_match_returns_none(self):
        result = match_warmup("今天天气怎么样")
        self.assertIsNone(result)

    def test_empty_question_returns_none(self):
        result = match_warmup("")
        self.assertIsNone(result)

    def test_normalized_match_handles_punctuation(self):
        result = match_warmup("测试公司何时成立？")
        self.assertEqual("测试公司成立于2020年。", result)


class WarmupNormalizeIdsTests(unittest.TestCase):
    def test_string_to_list(self):
        self.assertEqual(["abc"], _normalize_ids("abc"))

    def test_list_preserved(self):
        self.assertEqual(["a", "b"], _normalize_ids(["a", "b"]))

    def test_none_returns_empty(self):
        self.assertEqual([], _normalize_ids(None))


class WarmupStripPrefixTests(unittest.TestCase):
    def test_strips_problem_prefix(self):
        self.assertEqual("你好", _strip_prefix("问题：你好", ("问题", "提问")))

    def test_no_prefix_unchanged(self):
        self.assertEqual("你好", _strip_prefix("你好", ("问题", "提问")))


if __name__ == "__main__":
    unittest.main()

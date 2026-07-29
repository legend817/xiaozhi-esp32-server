import unittest

from core.utils.rag_context import (
    build_enterprise_faq_cache_alias,
    build_enterprise_faq_retrieval_question,
    extract_entity_query_term,
    filter_contexts_containing_term,
    select_enterprise_location_answer,
    select_direct_qa_answer,
    select_rag_contexts,
    select_staged_rag_first_sentence,
)


class SelectRagContextsTests(unittest.TestCase):
    def test_builds_strict_enterprise_faq_aliases(self):
        self.assertEqual(
            ("phone", "phone:公司"),
            build_enterprise_faq_cache_alias("查一下公司的电话。"),
        )
        self.assertEqual(
            ("phone", "phone:中科生创集团"),
            build_enterprise_faq_cache_alias("中科生创集团的联系电话是多少？"),
        )
        self.assertEqual(
            ("org_address", "org_address:公司"),
            build_enterprise_faq_cache_alias("请问公司地址是什么？"),
        )
        self.assertEqual(
            ("main_business", "main_business:集团"),
            build_enterprise_faq_cache_alias("集团的主要业务是什么？"),
        )
        self.assertEqual(
            ("personnel_count", "personnel_count:公司:科学家"),
            build_enterprise_faq_cache_alias("公司一共有多少位科学家？"),
        )
        self.assertEqual(
            ("", ""),
            build_enterprise_faq_cache_alias("公司有多少位科学家，分别是谁？"),
        )

    def test_does_not_alias_ambiguous_or_explanatory_questions(self):
        self.assertEqual(
            ("", ""), build_enterprise_faq_cache_alias("林晓锋的电话是多少？")
        )
        self.assertEqual(
            ("", ""), build_enterprise_faq_cache_alias("临床应用中心地址在哪里？")
        )
        self.assertEqual(
            ("", ""), build_enterprise_faq_cache_alias("详细介绍一下公司的主营业务")
        )
        self.assertEqual(
            ("", ""),
            build_enterprise_faq_cache_alias(
                "中科生创集团（福建）有限公司是在哪些机构支持下创办的？"
            ),
        )

    def test_rewrites_enterprise_location_query_for_retrieval(self):
        category, alias = build_enterprise_faq_cache_alias("中科生创集团在哪里？")

        self.assertEqual("org_address", category)
        self.assertEqual(
            "中科生创集团 地址",
            build_enterprise_faq_retrieval_question(
                "中科生创集团在哪里？", category, alias
            ),
        )

    def test_person_alias_is_scoped_by_name(self):
        self.assertEqual(
            ("person", "person:林晓锋"),
            build_enterprise_faq_cache_alias("林晓锋是谁？"),
        )
        self.assertEqual(
            ("person", "person:张三"),
            build_enterprise_faq_cache_alias("张三是什么人？"),
        )

    def test_deduplicates_qa_aliases_by_answer(self):
        contents = [
            "问题：公司电话是多少？\n回答：联系电话是 400-123-4567。",
            "问题：怎么联系公司？\n回答：联系电话是 400-123-4567。",
            "问题：公司地址在哪里？\n回答：公司位于北京市海淀区。",
        ]

        selected, duplicates = select_rag_contexts(contents, 3, 2200)

        self.assertEqual(2, len(selected))
        self.assertEqual(1, duplicates)
        self.assertIn("公司地址", selected[1])

    def test_keeps_distinct_non_qa_chunks(self):
        contents = ["公司成立于2021年。", "公司主营医疗科技服务。"]

        selected, duplicates = select_rag_contexts(contents, 3, 2200)

        self.assertEqual(contents, selected)
        self.assertEqual(0, duplicates)

    def test_applies_chunk_and_character_limits_after_deduplication(self):
        contents = [
            "问题：问法一\n回答：同一个答案",
            "问题：问法二\n回答：同一个答案",
            "问题：问法三\n回答：第二个答案很长",
            "问题：问法四\n回答：第三个答案",
        ]

        selected, duplicates = select_rag_contexts(contents, 2, 35)

        self.assertEqual(2, len(selected))
        self.assertEqual(1, duplicates)
        self.assertLessEqual(sum(len(item) for item in selected), 35)

    def test_extracts_only_tightly_scoped_person_questions(self):
        self.assertEqual("林晓锋", extract_entity_query_term("林晓锋是谁？"))
        self.assertEqual("林晓锋", extract_entity_query_term("请介绍一下林晓锋"))
        self.assertEqual("", extract_entity_query_term("公司有多少位科学家？"))
        self.assertEqual("", extract_entity_query_term("分别是谁？"))
        self.assertEqual("", extract_entity_query_term("请介绍一下。"))

    def test_entity_fallback_requires_explicit_name_in_chunk(self):
        chunks = [
            {"content": "问题：林晓锋是谁？\t回答：林晓锋是集团CEO。"},
            {"content": "问题：公司电话？\t回答：0591-87699999。"},
        ]

        self.assertEqual(
            [chunks[0]], filter_contexts_containing_term(chunks, "林晓锋")
        )

    def test_direct_answer_uses_exact_qa_question(self):
        chunks = [
            {
                "similarity": 0.51,
                "content": "问题：公司的地址在哪里？\t回答：公司位于鼓楼区。",
            },
            {
                "similarity": 0.51,
                "content": "问题：详细介绍公司地址\t回答：这是一段需要归纳的长资料。",
            },
        ]

        self.assertEqual(
            "公司位于鼓楼区。",
            select_direct_qa_answer("公司的地址在哪里？", chunks),
        )

    def test_direct_answer_requires_alias_consensus_without_exact_match(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "问题：公司电话？\t回答：联系电话是0591-87699999。",
            },
            {
                "similarity": 0.45,
                "content": "问题：怎么联系公司？\t回答：联系电话是0591-87699999。",
            },
            {
                "similarity": 0.38,
                "content": "问题：公司地址？\t回答：公司位于鼓楼区。",
            },
        ]

        self.assertEqual(
            "联系电话是0591-87699999。",
            select_direct_qa_answer("公司的联系电话是多少？", chunks),
        )

    def test_direct_count_answer_omits_unrequested_name_list(self):
        chunks = [
            {
                "similarity": 0.38,
                "content": "问题：公司有几位科学家？\t回答：公司共有九位科学家，分别为：甲、乙、丙。",
            },
            {
                "similarity": 0.38,
                "content": "问题：科学家数量？\t回答：公司共有九位科学家，分别为：甲、乙、丙。",
            },
        ]

        self.assertEqual(
            "公司共有九位科学家。",
            select_direct_qa_answer("公司有多少位科学家？", chunks),
        )

    def test_direct_count_answer_keeps_requested_name_list_or_falls_back(self):
        short_chunks = [
            {
                "similarity": 0.38,
                "content": "问题：公司有几位科学家，分别是谁？\t回答：公司共有三位科学家，分别为甲、乙、丙。",
            },
            {
                "similarity": 0.38,
                "content": "问题：科学家名单？\t回答：公司共有三位科学家，分别为甲、乙、丙。",
            },
        ]
        long_chunks = [
            {
                "similarity": 0.38,
                "content": "问题：公司有几位科学家，分别是谁？\t回答：公司共有九位科学家，分别为甲、乙、丙、丁、戊、己、庚、辛、壬，覆盖多个研究方向。",
            },
            {
                "similarity": 0.38,
                "content": "问题：科学家名单？\t回答：公司共有九位科学家，分别为甲、乙、丙、丁、戊、己、庚、辛、壬，覆盖多个研究方向。",
            },
        ]

        self.assertEqual(
            "公司共有三位科学家，分别为甲、乙、丙。",
            select_direct_qa_answer("公司有多少位科学家，分别是谁？", short_chunks),
        )
        self.assertEqual(
            "",
            select_direct_qa_answer(
                "公司有多少位科学家，分别是谁？", long_chunks, max_chars=30
            ),
        )

    def test_direct_answer_normalizes_phone_separator_spaces(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "问题：公司电话？\t回答：联系电话是0591- 87699999。",
            },
            {
                "similarity": 0.45,
                "content": "问题：怎么联系公司？\t回答：联系电话是0591- 87699999。",
            },
        ]

        self.assertEqual(
            "联系电话是0591-87699999。",
            select_direct_qa_answer("公司的联系电话是多少？", chunks),
        )

    def test_direct_answer_location_aliases(self):
        chunks = [
            {
                "similarity": 0.92,
                "content": "问题：中科生创集团在哪里？\n回答：中科生创集团的地址是福建省福州市鼓楼区水部街道五一中路18号。",
            },
            {
                "similarity": 0.89,
                "content": "问题：中科生创集团在什么地方？\n回答：中科生创集团的地址是福建省福州市鼓楼区水部街道五一中路18号。",
            },
        ]
        self.assertEqual(
            "中科生创集团的地址是福建省福州市鼓楼区水部街道五一中路18号。",
            select_direct_qa_answer("中科生创集团在什么地方。", chunks),
        )

    def test_direct_answer_flattened_qa_row(self):
        chunks = [
            {
                "similarity": 0.92,
                "content": "问题：中科生创集团在哪里？ 回答：中科生创集团的地址是福建省福州市。",
            },
            {
                "similarity": 0.90,
                "content": "问题：请问中科生创集团在哪里？ 回答：中科生创集团的地址是福建省福州市。",
            },
        ]
        self.assertEqual(
            "中科生创集团的地址是福建省福州市。",
            select_direct_qa_answer("中科生创集团在哪里？", chunks),
        )

    def test_select_enterprise_location_answer_trims_mixed_context_prefix(self):
        chunks = [
            {
                "similarity": 0.42,
                "content": "中科生创集团与国家区域医疗中心复旦大学华山附属医院福建医院、中科生创集团总部位于中国福建省福州市。",
            }
        ]

        self.assertEqual(
            "中科生创集团总部位于中国福建省福州市。",
            select_enterprise_location_answer(
                "中科生创集团在哪里？", chunks, subject="中科生创集团"
            ),
        )

    def test_select_enterprise_location_answer_prefers_full_address_sentence(self):
        chunks = [
            {
                "similarity": 0.42,
                "content": "问题：中科生创集团地址？ 回答：中科生创集团的地址是福建省福州市鼓楼区水部街道五一中路18号正大广场1号楼。",
            }
        ]

        self.assertEqual(
            "中科生创集团的地址是福建省福州市鼓楼区水部街道五一中路18号正大广场1号楼。",
            select_enterprise_location_answer(
                "中科生创集团在哪里？", chunks, subject="中科生创集团"
            ),
        )

    def test_direct_location_answer_keeps_only_address_sentence(self):
        chunks = [
            {
                "similarity": 0.92,
                "content": "问题：中科生创集团地址？ 回答：中科生创集团总部地址为福建省福州市鼓楼区水部街道五一中路18号正大广场1#楼1层、2层。其中一层设有智慧医疗科技长廊。",
            },
            {
                "similarity": 0.90,
                "content": "问题：中科生创集团在哪里？ 回答：中科生创集团总部地址为福建省福州市鼓楼区水部街道五一中路18号正大广场1#楼1层、2层。其中一层设有智慧医疗科技长廊。",
            },
        ]

        self.assertEqual(
            "中科生创集团总部地址为福建省福州市鼓楼区水部街道五一中路18号正大广场1#楼1层、2层。",
            select_direct_qa_answer("中科生创集团在哪里？", chunks, max_chars=120),
        )

    def test_select_staged_rag_first_sentence_from_qa_answer(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "问题：详细介绍公司\t回答：公司是生物科技企业，聚焦医疗器械产业化。第二句继续介绍。",
            }
        ]

        self.assertEqual(
            "公司是生物科技企业，聚焦医疗器械产业化。",
            select_staged_rag_first_sentence("请详细介绍公司", chunks),
        )

    def test_select_staged_rag_first_sentence_from_plain_chunk(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "中科生创集团总部位于福州。集团聚焦生物医药转化。",
            }
        ]

        self.assertEqual(
            "中科生创集团总部位于福州。",
            select_staged_rag_first_sentence("介绍一下中科生创集团", chunks),
        )

    def test_select_staged_rag_first_sentence_allows_comma_boundary(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "中科生创集团的临床应用中心位于福州国际医疗综合试验区，与复旦大学附属华山医院福建医院共建。",
            }
        ]

        self.assertEqual(
            "中科生创集团的临床应用中心位于福州国际医疗综合试验区，",
            select_staged_rag_first_sentence("请详细介绍一下中科生创集团", chunks),
        )

    def test_select_staged_rag_first_sentence_skips_detail_list_questions(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "问题：公司有多少位科学家？\t回答：公司共有九位科学家，分别为甲、乙、丙。",
            }
        ]

        self.assertEqual(
            "",
            select_staged_rag_first_sentence("公司有多少位科学家，分别是谁？", chunks),
        )

    def test_select_staged_rag_first_sentence_never_hard_truncates_fact(self):
        chunks = [
            {
                "similarity": 0.45,
                "content": "中科生创集团的临床应用中心是在福州国际医疗综合试验区与复旦大学附属华山医院福建医院共建的重要平台",
            }
        ]

        self.assertEqual(
            "",
            select_staged_rag_first_sentence("请详细介绍一下中科生创集团", chunks),
        )

    def test_direct_answer_falls_back_for_explanation_or_conflict(self):
        explanation_chunks = [
            {
                "similarity": 0.52,
                "content": "问题：详细介绍临床中心\t回答：临床中心的详细资料。",
            }
        ]
        conflicting_chunks = [
            {
                "similarity": 0.45,
                "content": "问题：问法一\t回答：答案一。",
            },
            {
                "similarity": 0.45,
                "content": "问题：问法二\t回答：答案一。",
            },
            {
                "similarity": 0.44,
                "content": "问题：问法三\t回答：答案二。",
            },
            {
                "similarity": 0.44,
                "content": "问题：问法四\t回答：答案二。",
            },
        ]

        self.assertEqual(
            "",
            select_direct_qa_answer("请详细介绍临床中心", explanation_chunks),
        )
        self.assertEqual(
            "",
            select_direct_qa_answer("请问相关情况？", conflicting_chunks),
        )


if __name__ == "__main__":
    unittest.main()

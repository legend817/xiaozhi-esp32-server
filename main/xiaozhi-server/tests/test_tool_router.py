import unittest

from core.utils.tool_router import build_tool_route


RAG_TOOL = ["search_from_ragflow"]
RAG_DESCRIPTION = (
    "如果用户询问与【中科生创公司信息_QA_v2】涵盖的主体范围相关内容时应调用本方法，"
    "用于查询：中科生创公司地址、电话、主营业务、团队、人员等等公司简介"
)


class ToolRouterEnterpriseRagTest(unittest.TestCase):
    def assert_rag(self, question):
        route = build_tool_route(question, RAG_TOOL, RAG_DESCRIPTION)
        self.assertEqual("enterprise_rag", route.name)
        self.assertEqual(RAG_TOOL, route.tool_names)

    def test_configured_company_name_routes_to_rag(self):
        self.assert_rag("中科生创有多少位科学家，分别是谁？")
        self.assert_rag("林晓锋是谁？中科生创里的")

    def test_generic_enterprise_information_routes_to_rag(self):
        self.assert_rag("这家公司主要是做什么的？")
        self.assert_rag("你们集团的临床应用中心在哪里？")
        self.assert_rag("你们公司的营业时间是几点？")

    def test_short_person_question_uses_enterprise_probe(self):
        route = build_tool_route("林晓锋是谁？", RAG_TOOL, RAG_DESCRIPTION)
        self.assertEqual("enterprise_rag_probe", route.name)
        self.assertEqual(RAG_TOOL, route.tool_names)

    def test_person_probe_requires_people_scope_in_description(self):
        route = build_tool_route(
            "林晓锋是谁？",
            RAG_TOOL,
            "查询【中科生创公司信息_QA_v3】中的地址和电话",
        )
        self.assertEqual("direct_llm", route.name)

    def test_unrelated_chat_stays_direct(self):
        route = build_tool_route("给我讲个笑话", RAG_TOOL, RAG_DESCRIPTION)
        self.assertEqual("direct_llm", route.name)
        self.assertEqual([], route.tool_names)


if __name__ == "__main__":
    unittest.main()

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


class ToolRouterVisionTest(unittest.TestCase):
    def test_visual_requests_select_camera_tool(self):
        for question in ("请调用摄像头拍一张照片", "帮我看看这是什么", "读取体检报告上的文字"):
            with self.subTest(question=question):
                route = build_tool_route(question, ["self_camera_take_photo"])
                self.assertEqual("vision", route.name)
                self.assertEqual(["self_camera_take_photo"], route.tool_names)

    def test_visual_request_without_camera_stays_direct(self):
        route = build_tool_route("帮我看看这是什么", ["self.get_device_status"])
        self.assertEqual("direct_llm", route.name)
        self.assertEqual([], route.tool_names)

    def test_colloquial_scene_requests(self):
        for question in (
            "你看看周围", "看看你面前的", "你看一下你的面前有什么",
            "帮我观察一下四周", "看看周边环境", "你看我手里拿的是什么",
            "我手上拿的是什么东西", "我穿的是什么颜色", "桌上有几个杯子",
            "你看见我手中的东西了吗", "你能看见我吗", "帮我看看这个",
            "这是什么东西", "读一下这张图片上面的文字", "识别文字",
            "你，看看，你面前的", "请打开摄像头看看外面的天气",
        ):
            with self.subTest(question=question):
                route = build_tool_route(question, ["self_camera_take_photo"])
                self.assertEqual("vision", route.name)
                self.assertEqual(["self_camera_take_photo"], route.tool_names)

    def test_camera_discussion_and_negation_do_not_capture(self):
        for question in (
            "不要打开摄像头", "别拍照", "不用看我周围", "关闭摄像头",
            "怎么打开摄像头", "推荐一款相机", "摄像头为什么不能用",
            "拍照的原理是什么", "这是什么概念", "这是什么意思",
            "我昨天拍的照片很好看", "体检报告是什么", "看看现在几点了",
            "帮我看看这个股票", "看看周围有什么餐厅推荐",
        ):
            with self.subTest(question=question):
                self.assertNotEqual("vision", build_tool_route(question, ["self_camera_take_photo"]).name)

    def test_information_requests_keep_existing_routes(self):
        tools = ["self_camera_take_photo", "get_weather", "get_news_from_newsnow", "search_from_ragflow"]
        for question, expected in (("帮我看看这两天天气", "weather"),
                                   ("看看今天的新闻", "news"),
                                   ("你们公司地址是什么", "enterprise_rag")):
            with self.subTest(question=question):
                self.assertEqual(expected, build_tool_route(question, tools).name)

    def test_visual_route_does_not_change_unrelated_chat(self):
        route = build_tool_route("请给我讲一个故事", ["self_camera_take_photo"])
        self.assertEqual("direct_llm", route.name)
        self.assertEqual([], route.tool_names)


if __name__ == "__main__":
    unittest.main()

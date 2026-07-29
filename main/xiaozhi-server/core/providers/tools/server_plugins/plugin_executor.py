"""服务端插件工具执行器"""

import asyncio
import json
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import all_function_registry, Action, ActionResponse


class ServerPluginExecutor(ToolExecutor):
    """服务端插件工具执行器"""

    def __init__(self, conn: "ConnectionHandler"):
        self.conn = conn
        self.config = conn.config

    async def execute(
        self, conn: "ConnectionHandler", tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行服务端插件工具"""
        func_item = all_function_registry.get(tool_name)
        if not func_item:
            return ActionResponse(
                action=Action.NOTFOUND, response=f"插件函数 {tool_name} 不存在"
            )

        try:
            # 根据工具类型决定如何调用
            if hasattr(func_item, "type"):
                func_type = func_item.type
                if func_type.code in [4, 5]:  # SYSTEM_CTL, IOT_CTL (需要conn参数)
                    result = func_item.func(conn, **arguments)
                elif func_type.code == 2:  # WAIT
                    result = func_item.func(**arguments)
                elif func_type.code == 3:  # CHANGE_SYS_PROMPT
                    result = func_item.func(conn, **arguments)
                else:
                    result = func_item.func(**arguments)
            else:
                # 默认不传conn参数
                result = func_item.func(**arguments)

            # 兼容 async def 工具函数
            if asyncio.iscoroutine(result):
                result = await result

            return result

        except Exception as e:
            return ActionResponse(
                action=Action.ERROR,
                response=str(e),
            )

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有注册的服务端插件工具"""
        tools = {}
        plugin_configs = self._get_plugin_configs()

        # 获取必要的函数
        necessary_functions = ["handle_exit_intent", "get_lunar"]

        intent_type = (
            self.config.get("Intent", {})
            .get(self.config.get("selected_module", {}).get("Intent"), {})
            .get("type")
        )

        # lightweight_router 不再使用 Intent.functions 白名单。
        # 可用工具只来自智能体已绑定插件，是否本轮挂载由 tool_router.py 决定。
        if intent_type == "lightweight_router":
            config_functions = []
        else:
            # 获取配置中的函数，保留原 function_call/intent_llm 配置文件兼容行为
            config_functions = self.config["Intent"][
                self.config["selected_module"]["Intent"]
            ].get("functions", [])

        # 转换为列表
        if not isinstance(config_functions, list):
            try:
                config_functions = list(config_functions)
            except TypeError:
                config_functions = []

        # 管理端下发的智能体绑定插件也纳入可用工具池。
        # lightweight_router 模式下，最终是否挂给 LLM 由轻量路由决定。
        configured_plugin_functions = [
            name
            for name in plugin_configs.keys()
            if name in all_function_registry
        ]

        # 合并所有需要的函数
        all_required_functions = list(
            set(necessary_functions + config_functions + configured_plugin_functions)
        )

        for func_name in all_required_functions:
            func_item = all_function_registry.get(func_name)
            if func_item:
                # 从函数注册中获取描述
                fun_description = (
                    plugin_configs
                    .get(func_name, {})
                    .get("description", "")
                )
                if fun_description is not None and len(fun_description) > 0:
                    if "function" in func_item.description and isinstance(
                        func_item.description["function"], dict
                    ):
                        func_item.description["function"][
                            "description"
                        ] = fun_description

                # 新闻插件：根据配置更新新闻源参数描述
                if func_name == "get_news_from_newsnow":
                    self._init_news_source_description(func_item, func_name)

                tools[func_name] = ToolDefinition(
                    name=func_name,
                    description=func_item.description,
                    tool_type=ToolType.SERVER_PLUGIN,
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的服务端插件工具"""
        return tool_name in all_function_registry

    def _get_plugin_configs(self) -> Dict[str, Dict[str, Any]]:
        """返回智能体已绑定插件配置，兼容管理端下发的JSON字符串参数。"""
        plugins = self.config.get("plugins") or {}
        result = {}
        for name, plugin_config in plugins.items():
            if isinstance(plugin_config, dict):
                result[name] = plugin_config
                continue
            if isinstance(plugin_config, str):
                try:
                    parsed = json.loads(plugin_config)
                except json.JSONDecodeError:
                    parsed = {}
                result[name] = parsed if isinstance(parsed, dict) else {}
                continue
            result[name] = {}
        return result

    def _init_news_source_description(self, func_item, func_name):
        """根据连接配置初始化新闻工具的参数描述"""
        news_sources = (
            self._get_plugin_configs()
            .get(func_name, {})
            .get("news_sources", "")
        )
        if not news_sources:
            news_sources = "澎湃新闻;百度热搜;财联社"
        sources_str = news_sources.replace(";", "、")
        try:
            func_item.description["function"]["parameters"]["properties"]["source"][
                "description"
            ] = f"新闻源的标准中文名称，例如{sources_str}等。可选参数，如果不提供则使用默认新闻源"
        except (KeyError, TypeError):
            pass

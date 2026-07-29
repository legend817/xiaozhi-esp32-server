# 工具路由优化记录

日期：2026-07-29

## 背景

全局启用 `Intent_function_call` 时，普通问答也会把所有工具描述传给 LLM。实测在 test 智能体上，普通企业问答会出现：

- `tools=true`
- `tool_count=8`
- 首包 TTS 明显变慢

但关闭意图识别后，普通问答恢复：

- `Intent_nointent`
- `tools=false`
- LLM 首 token 和 TTS 首包恢复到较快路径

问题是：完全 `nointent` 的语义应保持为“无意图、无工具”，不能为了优化工具调用而改变原有行为。
如果要兼顾低延迟和按需工具调用，应使用独立的意图识别选项。

## 当前方案

新增 `Intent_lightweight_router`（轻量工具路由）：

- `Intent_nointent` 保持原始行为：不加载工具、不暴露工具、直接进入普通 LLM 对话
- `Intent_lightweight_router` 才启用轻量工具路由
- 默认直接 LLM：`tools=false`
- 只有用户问题明确命中某类能力时，才给 LLM 暴露对应工具
- 不使用额外 LLM 做意图识别，避免引入新的前置延迟
- 设备音量/亮度/主题等明确控制指令走确定性执行，不再让 LLM 自由决定工具链

核心文件：

- `main/xiaozhi-server/core/utils/tool_router.py`
- `main/xiaozhi-server/core/connection.py`
- `main/xiaozhi-server/core/providers/intent/lightweight_router/lightweight_router.py`
- `main/xiaozhi-server/core/providers/tools/server_plugins/plugin_executor.py`

管理端配置：

- Provider：`SYSTEM_Intent_lightweight_router`
- Model config：`Intent_lightweight_router`
- type：`lightweight_router`

## 路由规则

仅当智能体选择 `Intent_lightweight_router` 时，当前支持的路由：

| route | 触发类型 | 暴露工具 |
|---|---|---|
| `direct_llm` | 普通聊天、笑话、解释类问题 | 无 |
| `exit` | 再见、拜拜、退出、待机 | `handle_exit_intent` |
| `device_volume` | 音量、声音、静音 | `self_get_device_status`, `self_audio_speaker_set_volume` |
| `device_brightness` | 屏幕亮度 | `self_get_device_status`, `self_screen_set_brightness` |
| `device_theme` | 深色/浅色主题 | `self_get_device_status`, `self_screen_set_theme` |
| `device_status` | 电量、网络、设备状态 | `self_get_device_status` |
| `music` | 播放音乐、听歌、有声书 | `play_music` 或 `hass_play_music` |
| `weather` | 天气、气温、下雨、空气质量 | `get_weather` |
| `time_lunar` | 农历、节气、生肖、宜忌 | `get_lunar` |
| `news` | 新闻、热搜、头条 | `get_news_from_newsnow` 或 `get_news_from_chinanews` |
| `enterprise_rag` | 公司、产品、价格、合作、案例等企业信息 | `search_from_ragflow` |
| `web_search` | 明确要求联网搜索 | `web_search` |

如果对应工具没有被管理端配置或设备 MCP 未上报，则自动退回 `direct_llm`。

## 运行验证

### 普通问答

问题：`给我讲个笑话`

日志：

```text
LATENCY event=tool_route route=direct_llm tools=false reason=no_rule_matched
LATENCY event=llm_request_start ... tools=false messages=2
```

结论：普通问答不再携带工具。

### 设备音量

问题：`把音量调到`

日志：

```text
LATENCY event=tool_route route=device_volume tools=['self_get_device_status', 'self_audio_speaker_set_volume', 'direct_answer']
LATENCY event=llm_request_start ... tools=true ... tool_count=3
```

结论：设备音量类问题只携带音量相关工具，不再携带全部工具。

### 设备音量确定性执行 v1

问题：`把音量调大一点`

日志：

```text
LATENCY event=tool_route route=device_volume tools=['self_get_device_status', 'self_audio_speaker_set_volume', 'direct_answer']
LATENCY event=tool_end name=self_get_device_status action=REQLLM ms=358 deterministic=true
LATENCY event=tool_end name=self_audio_speaker_set_volume action=REQLLM ms=18 deterministic=true
LATENCY event=chat_end depth=0 total_ms=383 tool_total_ms=376 tool_count=2
LATENCY event=tts_first_audio ms=685
```

结论：

- 后端直接执行 `get_device_status` 和 `set_volume`
- 没有进入 LLM function_call 决策
- 当前音量为 0，目标音量计算为 10
- 首包 TTS 约 685ms
- 全链路播报结束约 2.6s

相比让 LLM 自行决定工具链，确定性执行更快且不会出现“只查询状态但回复已设置”的错误。

## 维护注意

1. 不要改变 `Intent_nointent` 的原始语义；它必须保持完全无工具。
2. 新增低延迟工具能力时，应挂到 `Intent_lightweight_router`。
3. 新增工具时，不要默认放进全局 function_call。
4. 先在 `tool_router.py` 增加明确规则。
5. 工具只在管理端已配置、或设备 MCP 已上报时才会进入可用池。
6. RAG 不应全局挂载，应通过 `enterprise_rag` route 按需触发。
7. 如果某类问题误触发工具，优先收紧关键词，不要重新打开全局意图识别。
8. 设备控制类优先确定性执行；只有规则无法解析时，才退回小工具集 function_call。

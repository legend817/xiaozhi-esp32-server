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
- 企业 RAG 问答命中 `enterprise_rag` 时走确定性 RAG 快路径，后端直接调用 `search_from_ragflow`，省掉第一轮 LLM 工具决策

核心文件：

- `main/xiaozhi-server/core/utils/tool_router.py`
- `main/xiaozhi-server/core/connection.py`
- `main/xiaozhi-server/core/providers/intent/lightweight_router/lightweight_router.py`
- `main/xiaozhi-server/core/providers/tools/server_plugins/plugin_executor.py`

管理端配置：

- Provider：`SYSTEM_Intent_lightweight_router`
- Model config：`Intent_lightweight_router`
- type：`lightweight_router`
- 不再配置 `functions` 白名单；可用工具来自智能体绑定插件

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
| `enterprise_rag_probe` | 知识库描述包含人员范围时的短人名问句 | `search_from_ragflow`；无命中直接安全拒答 |
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
9. 企业 RAG 类优先确定性执行；只有规则无法确定为企业知识库问题时，才退回普通 LLM 或小工具集。
10. `Intent_lightweight_router` 不再维护 `Intent.functions` 白名单。新增工具的维护顺序是：
    1. 在管理端给智能体绑定插件并配置参数；
    2. 在 `tool_router.py` 增加明确路由规则；
    3. 必要时在 `connection.py` 增加确定性执行分支。
11. 企业名称从智能体绑定的 `search_from_ragflow` 插件描述中动态提取；新增企业知识库时应在描述中保留清晰的企业名称，不需要把企业名硬编码到路由器。
12. RAG 没有召回 chunk 时直接回复“知识库里暂时没有这项信息”，不再交给 LLM 补写，避免幻觉并减少一次生成耗时。

## 企业 RAG 确定性执行 v1

问题：`中科生创公司是做什么的？`

优化前，`Intent_function_call` 会先让 LLM 决定是否调用 RAG：

```text
chat_end total_ms=5574
tts_first_audio ms=5697
```

优化后，`Intent_lightweight_router` 命中 `enterprise_rag` 时，后端直接执行 RAG：

```text
LATENCY event=tool_route route=enterprise_rag tools=['search_from_ragflow', 'direct_answer']
LATENCY event=deterministic_tool_route route=enterprise_rag tool=search_from_ragflow
LATENCY event=ragflow_retrieval ms=903
LATENCY event=ragflow_context chunks=3 selected_chunks=3 selected_chars=1739 page_size=3 top_k=16 similarity_threshold=0.3
LATENCY event=chat_end total_ms=2496
LATENCY event=tts_first_audio ms=2602
```

结论：

- 省掉第一轮 LLM 工具决策；
- RAGFlow 返回上下文从默认约 30 个 chunk 收敛到 3 个 chunk；
- LLM 二次总结输入明显减少；
- 企业信息问答当前不需要 staged RAG，先直接等 RAG 返回后回答。

## RAGFlow 上下文缓存 v1

对高频企业问题，`search_from_ragflow` 会先检查进程内缓存：

```text
LATENCY event=ragflow_cache hit=true key=...
```

缓存命中后直接把上次的 RAGFlow 上下文交给 LLM，总体链路仍是：

```text
tool_router.py 判断 enterprise_rag
  ↓
search_from_ragflow 命中缓存
  ↓
LLM 根据缓存上下文生成答案
  ↓
TTS 播放
```

缓存键包含：

- 归一化后的用户问题
- RAGFlow `base_url`
- `dataset_ids`
- `page_size`
- `top_k`
- `similarity_threshold`
- `max_context_chunks`
- `max_context_chars`

默认参数：

```yaml
cache_enabled: true
cache_ttl: 600
```

注意：

- 这是 RAGFlow 上下文缓存，不是最终答案缓存；
- 修改知识库后，最多可能有 `cache_ttl` 秒旧上下文窗口；
- 如果知识库更新频繁，把 `cache_ttl` 调短或临时设置 `cache_enabled: false`。

2026-07-29 回测：

```text
冷缓存:
LATENCY event=ragflow_cache hit=false
LATENCY event=ragflow_retrieval ms=1027
LATENCY event=chat_end total_ms=2489
LATENCY event=tts_first_audio ms=2527

热缓存:
LATENCY event=ragflow_cache hit=true
LATENCY event=tool_end name=search_from_ragflow ms=6
LATENCY event=chat_end total_ms=1114
LATENCY event=tts_first_audio ms=1196
```

## Q&A 别名去重 v1

企业 Q&A v3 使用“一种问法一行”的结构提高精确召回，同一标准答案会对应多个问法。RAGFlow 可能一次返回同一答案的多个别名，因此服务端在限制上下文之前按“回答正文”去重：

```text
RAGFlow 返回多个 chunk
  ↓
提取“回答：”之后的正文作为去重键
  ↓
移除重复答案
  ↓
再应用 max_context_chunks / max_context_chars
```

日志新增 `duplicate_answers`：

```text
LATENCY event=ragflow_context chunks=3 selected_chunks=2 duplicate_answers=1 ...
```

非 Q&A 文档没有“回答：”标记时，仍按完整正文去重，不影响普通知识文档。相关实现和回归测试：

- `core/utils/rag_context.py`
- `tests/test_rag_context.py`

## 人名检索与输出安全 v1

- 普通 RAG 仍使用 `similarity_threshold=0.3`；
- 只有“某某是谁/是什么人/做什么的”等严格短人名问句使用 `entity_fallback_threshold=0.18`；
- 低阈值结果必须逐字包含查询姓名，否则视为无命中；
- 无命中直接回复企业知识库没有该人员资料，不让 LLM 猜测；
- 轻量路由只在知识库描述明确包含“人员/团队/员工/专家/科学家”范围时启用人名探测；
- LLM 即使把工具调用 JSON 当普通文字输出，也会从 `{`/`<` 前缀开始缓冲，确认是工具调用后整段禁止进入 TTS。

默认配置：

```yaml
similarity_threshold: 0.3
entity_fallback_threshold: 0.18
```

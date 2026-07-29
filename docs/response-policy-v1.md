# ResponsePolicy_V1 回复预算控制

## 目的

降低语音链路中的 TTS 播报时长，避免 LLM 输出过长拖慢完整响应。

该策略不是“讲笑话专用截断”，而是面向后续企业客服、知识库、陪伴聊天等场景的通用回复预算框架。

## 当前实现

代码入口：

- `main/xiaozhi-server/core/utils/response_policy.py`
- `main/xiaozhi-server/core/connection.py`

处理流程：

```text
用户输入
  ↓
build_response_policy(query)
  ↓
向本轮 LLM dialogue 临时注入 ResponsePolicy_V1 system 约束
  ↓
流式接收 LLM 输出
  ↓
过滤“要继续听吗”等禁止续问
  ↓
ResponseBudget 控制送入 TTS 的文本长度
  ↓
超过预算后继续消费 LLM 流，但不再继续送 TTS
```

策略约束是“本轮临时注入”，不会写入长期对话历史。

## 当前策略

| 策略 | 触发 | 字数预算 | 兜底 |
| --- | --- | ---: | --- |
| `joke` | 笑话、冷笑话、段子 | 40 | 遇到第一个完整句子结束符即停止 |
| `enterprise_qa` | 企业、公司、产品、服务、价格、合作、联系方式等 | 75 | 超长后停止继续送 TTS，不主动续问 |
| `enterprise_explain` | 企业 RAG 中明确要求详细、介绍、原因、原理、对比等 | 120 | 最多2个完整句子，不开始无法收尾的新事实 |
| `explain` | 为什么、如何、方案、步骤、知识库等 | 90 | 超长后停止继续送 TTS，不主动续问 |
| `fast_default` | 默认 | 60 | 超长后停止继续送 TTS |

所有策略都会追加主题隔离规则：

```text
本轮必须优先回答当前用户问题；上一轮对话只作语气参考，
不得延续上一轮业务场景。若当前问题与上一轮无关，必须立即切换主题。
```

## 已验证

真实 ESP32 测试中：

- `讲个笑话` 命中 `joke`
- `企业产品/服务/价格/联系方式` 类问题命中 `enterprise_qa`

日志示例：

```text
LATENCY event=response_policy trace=... policy=joke max_chars=40 suffix=False
LATENCY event=response_policy trace=... policy=enterprise_qa max_chars=75 suffix=False
```

## 已知取舍

- V1 直接按关键词分类，足够轻量，但不是完整意图识别。
- 后处理只控制送入 TTS 的文本；LLM 流仍会被消费完，避免连接异常。
- 对企业客服类问题不硬切 40 字，避免把关键企业信息截断。
- 已移除退款、订单、物流等售后/电商类触发词；当前项目暂不面向这类场景。
- 当前企业客服/解释预算已收紧，目标是优先保证首响应，不在第一轮输出完整长答案。
- 默认不追加“要继续听吗/要我继续介绍吗”这类续问，避免语音交互显得啰嗦。
- 禁止续问采用流式前缀缓冲，即使“要/继续听/吗”分成多个 token，也不会有前半句先进入 TTS。
- RAG 工具执行后的第二次 LLM 继续沿用用户首轮的回复策略，不再退回 `fast_default` 导致中途截断。
- `enterprise_rag` / `enterprise_rag_probe` 路由会强制选择 `enterprise_qa`，即使原问题只含“集团、临床、科学家”等词，也不会错误使用 60 字 `fast_default`。
- 企业问答要求只回答用户所问字段，不扩展相邻事实；“临床中心在哪里”只回答位置和必要共建信息。
- 企业 RAG 遇到“详细介绍、为什么、如何、对比”等解释请求时使用 `enterprise_explain`，避免被普通企业问答的 75 字预算截成残句。
- 超过硬字数预算时至少补终止标点；企业问答提示目标收紧到 55 字，给 75 字硬上限保留完整收尾空间。
- 后续应迁移到智能体配置，例如：

```yaml
response_policy:
  mode: enterprise_qa
  default_max_chars: 80
  enterprise_qa_max_chars: 100
  explain_max_chars: 140
```

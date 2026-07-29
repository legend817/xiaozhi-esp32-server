# 企业客服 RAG 优化计划

## 背景

目标场景是企业客服/企业信息问答，不是电商售后客服。

典型问题：

- 公司主要做什么
- 产品有哪些
- 价格/套餐是多少
- 怎么合作
- 联系方式是什么
- 有哪些客户案例
- 企业资质、合同、发票、服务流程

这些问题多数需要依赖企业知识库，不能让 LLM 凭空编答案。因此 RAG 的真实耗时会直接影响语音体验。

## 当前决策原则

先测 RAG 真实耗时，再决定是否做“两段式回答”。

不先凭感觉改交互。

## 2026-07-29 实测结论

当前 test 智能体使用：

- Intent：`Intent_lightweight_router`
- LLM：`Qwen3-30B-A3B`
- ASR：`ASR_FunASRServer2Pass`
- TTS：`TTS_HuoshanDoubleStreamTTS`
- RAG：RAGFlow，知识库 `中科生创公司信息`

问题：

```text
中科生创公司是做什么的？
```

阶段性结果：

| 方案 | chat_end | TTS 首音频 | 关键特征 |
|---|---:|---:|---|
| `Intent_function_call` 原始 RAG | 5574 ms | 5697 ms | LLM 先判断工具，再查 RAG，再二次 LLM |
| `Intent_lightweight_router` 小工具集 | 4578 ms | 4938 ms | 只暴露 `search_from_ragflow` 与 `direct_answer` |
| 轻量路由确定性 RAG | 3477 ms | 3633 ms | 后端直接调用 RAG，省掉第一轮 LLM 工具决策 |
| 确定性 RAG + 检索参数收敛 | 2496 ms | 2602 ms | `page_size=3`、`top_k=16`、`similarity_threshold=0.3` |

结论：

- 当前 RAG 检索本身约 0.8～1.1 秒，暂不需要 staged RAG。
- 最大收益来自绕过第一轮 LLM 工具决策，以及减少 RAG 返回上下文。
- 企业信息问答可以先采用“等 RAG 后直接回答”，不需要先播“我查一下资料”。
- 如果后续知识库变大或 RAGFlow 检索超过 1500 ms，再启用 staged RAG。

当前默认策略：

```text
轻量路由命中 enterprise_rag
  ↓
后端直接调用 search_from_ragflow(question=原问题)
  ↓
RAGFlow 返回少量高相关 chunk
  ↓
只做一次 LLM 总结
  ↓
TTS 播放答案
```

维护注意：

- 不要让 `enterprise_rag` 再走完整 function_call 工具决策链。
- RAGFlow 默认返回 chunk 不宜过多；语音客服优先短答案。
- RAG 插件默认参数可被插件配置覆盖：
  - `page_size`
  - `top_k`
  - `similarity_threshold`
  - `max_context_chunks`
  - `max_context_chars`
- 如果出现查不全，再优先调大 `page_size/max_context_chunks`，不要直接恢复到 30 个 chunk。

## 候选交互策略

### 1. 直接回答

适用：

- 低风险问题
- 不依赖企业事实
- 例如“你能帮我了解公司吗”

特点：

- 最自然
- 不查 RAG
- 延迟最低

### 2. 缓存回答

适用：

- 高频企业问题
- 最近已经查过 RAG
- 缓存仍有效

特点：

- 体验最好
- 可以直接回答事实
- 后续应重点建设

### 3. 等 RAG 后回答

适用：

- RAG 检索足够快

判断标准：

```text
RAG < 700ms
```

特点：

- 不需要先说“我查一下”
- 体验仍然自然
- 答案可靠

### 4. 两段式 staged RAG

适用：

- RAG 检索明显慢

判断标准：

```text
RAG > 1500ms
```

流程：

```text
用户提问
  ↓
立即播短确认：我看下资料，给你准确说法。
  ↓
后台并行查 RAG
  ↓
RAG 返回后生成短答案
  ↓
第二句无缝接上
```

原则：

- 第一短句不能编企业事实
- 第二句必须基于 RAG
- 查不到时明确说资料里没查到

## 阈值建议

```text
RAG < 700ms:
  直接等 RAG，再回答

RAG 700ms～1500ms:
  先不做复杂两段式，可继续观察首音频体感

RAG > 1500ms:
  做 staged RAG
```

## 下一步测试顺序

### 阶段 1：不开 RAG，只测意图识别开销

用户会先启用意图识别。

测试目标：

- 意图识别是否会显著拖慢首响应
- 是否误触发工具/RAG
- `Intent` 模块实际耗时
- LLM 首 token 是否上升
- TTS 首音频是否上升

测试句：

```text
你们公司是做什么的
产品价格是多少
怎么联系你们
```

当前预期：

- 先不开 RAG
- 只验证意图识别对企业客服问题的链路影响
- 如果意图识别开销明显，再考虑是否继续使用 `Intent_nointent` + 轻量关键词策略

### 阶段 2：开启 RAG 后测真实耗时

后续再开启 RAG。

需要记录：

```text
rag_start
rag_end
rag_ms
rag_hit_count
llm_first_token
tts_first_audio
tts_end
```

测试句：

```text
你们公司是做什么的
产品价格是多少
怎么联系你们
```

### 阶段 3：决定交互策略

根据 RAG 实测耗时选择：

- 直接等 RAG
- 缓存优先
- staged RAG

## 当前不做

- 不立刻实现 staged RAG
- 不立刻接入企业客服 RAG
- 不用 LLM 猜企业事实
- 不恢复退款/订单/物流类售后客服策略

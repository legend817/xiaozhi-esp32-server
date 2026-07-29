# VAD -> ASR -> LLM -> TTS 链路优化记录

## 当前结论

抛开模型推理速度，链路仍有优化空间，但不能盲目改默认阈值。

源码示例中的 SileroVAD 配置曾为：

```yaml
VAD:
  SileroVAD:
    min_silence_duration_ms: 200
```

但管理端数据库实际下发值原为 `700ms`，真实 ESP32 日志为约 `712～745ms`。因此运行值不能只看源码示例，必须以管理端配置和 `vad_voice_stop` 日志为准。

## 已增加打点

新增 VAD/ASR 边界日志：

```text
LATENCY event=vad_first_voice trace=...
LATENCY event=vad_voice_stop trace=... silence_ms=... speech_ms=... buffered_frames=... buffered_bytes=...
LATENCY event=asr_start trace=... vad_to_asr_ms=...
LATENCY event=asr_end trace=... ms=...
```

这些日志用于后续接入 ESP32 或真实音频后拆分：

- 首次检测到人声的时间
- VAD 判定说话结束的时间
- VAD 判停到 ASR 开始之间是否有线程/队列等待
- ASR 本身耗时

## 为什么先打点

当前无 ESP32 条件下，文本和合成音测试无法真实覆盖：

- 设备端 Opus 上传节奏
- VAD 真实误判/漏判
- 用户说话尾音、停顿、环境噪声
- AEC 场景下的 VAD 干扰

真实设备验证也证明，直接把 `min_silence_duration_ms` 从 700ms 改为固定 550ms，会把带停顿的“请介绍一下……中科生创集团……”截成两轮。因此最终采用下文记录的自适应句尾策略，而不是固定低阈值。

## 可优化方向

### 1. VAD 尾部策略

后续可做成分档：

| 场景 | silence threshold |
| --- | ---: |
| 完整短命令、短问答 | 550ms（当前实测档位） |
| partial 明显未说完 | 900ms（当前保护档位） |
| 手动模式 | 不使用实时 VAD 判停 |

需要真实音频验证后再改。

### 2. ASR 流式化

当前 `FunASRServer` provider 以 offline 模式发送完整 PCM：

```json
{"mode": "offline"}
```

它比本地 FunASR 快，但仍是“说完后提交整段”。如果要继续压首响应，应评估 FunASR runtime 的 online / 2-pass 接入，让 ASR 在用户说话过程中提前处理。

目标：把“说完后 ASR 约 541ms”压到“说完后 100～300ms 内 final”。

已新增旁路 provider：`core/providers/asr/fun_server_2pass.py`。

- 原 `fun_server` 保留，作为稳定 offline 回退。
- 新 `fun_server_2pass` 在 VAD 检测到语音开始后立即打开 WebSocket，并把后续 PCM 帧持续转发给 FunASR runtime。
- 新 provider 记录 `funasr_2pass_start`、`funasr_2pass_partial`、`funasr_2pass_final`。
- 当前只用 `2pass-offline` final 触发 LLM，不用 partial 抢跑，避免误识别导致错误回复。
- 管理端已注册新模型配置 `ASR_FunASRServer2Pass`，可在智能体 ASR 配置中切换验证。

### 3. TTS 首音频

火山双流 provider 已经是边收 LLM delta 边发给火山，瓶颈更多在：

- 火山服务首包
- 并发连接
- 文本输出长度
- 连接复用状态

后续重点不是通用分句，而是监控：

- `tts_first_audio_ms`
- `tts_audio_total_ms`
- 并发下 P95

## 下一步建议

1. 重建并重启服务，使 VAD/ASR 打点生效。
2. 有 ESP32 后用真实语音跑一次，抓取 `vad_first_voice` 到 `tts_first_audio` 全链路。
3. 再决定是否调整 VAD 阈值或接入 FunASR online/2-pass。

## 2026-07-29：FunASR 企业专名热词与纠错

真实 ESP32 测试中，`林晓锋是谁` 被 2-pass final 识别为 `林晓峰是谁`。RAG 的精确姓名保护正确拒绝了错误姓名，但企业专名问答因此失败。

`fun_server_2pass` 现支持两个可选配置：

```yaml
hotwords:
  林晓锋: 30
  中科生创: 20
text_corrections:
  林晓峰: 林晓锋
```

- `hotwords` 会序列化为 FunASR WebSocket 初始化协议中的动态热词字段，无须要求 FunASR 启动命令必须包含 `--hotword`；
- `text_corrections` 只作用于 2-pass final 文本，是模型热词仍未纠正时的确定性兜底；
- 词表属于具体部署数据，维护在管理端 ASR 模型配置中，不硬编码在 provider；
- 日志只记录热词/纠错数量和是否发生替换，不打印完整词表。

如果希望同一 FunASRServer 的所有客户端共享热词，也可以在 FunASR 宿主机的 `hotwords.txt` 中按 `词 权重` 每行配置，并通过 `run_server_2pass.sh --hotword ...` 加载；这是服务端静态热词，与当前按会话动态下发可以并存。

当前 test 环境的 `ASR_FunASRServer2Pass` 已配置：

```text
hotwords = {林晓锋: 30, 中科生创: 20}
text_corrections = {林晓峰: 林晓锋}
```

### 后续维护热词的标准流程

1. 先确认作用范围。多个智能体绑定同一个 ASR 模型配置时，会共享这份动态热词；需要隔离企业词表时，应复制一份 ASR 模型配置并绑定给对应智能体。
2. 在 `ASR_FunASRServer2Pass` 的 `config_json` 中维护两个对象：
   - `hotwords`：正确词到权重的映射，例如 `{"新产品名": 20}`；
   - `text_corrections`：常见错误结果到正确词的映射，例如 `{"新产平名": "新产品名"}`。
3. 新词先只加入 `hotwords`，从 15～20 的权重开始实测；只有稳定出现同一种误识别时，才增加 `text_corrections`。纠错是精确文本替换，不应配置“公司”“中心”等可能在普通语句中出现的通用词。
4. 如果绕过管理接口直接更新数据库，需要精确删除 Redis 的 `model:data:ASR_FunASRServer2Pass` 和 `server:config` 两个缓存键，并重建 `xiaozhi-esp32-server` 容器。不得使用 `FLUSHDB` 清空全部缓存。
5. ESP32 断开并重新连接后，用真实语音验证；启动日志中的 `hotword_count`、`correction_count` 应与配置数量一致。

当前管理端尚未注册 `FunASRServer2Pass` 的可视化字段，因此页面暂时不能直接维护这两个对象。长期方案是在 `ai_model_provider` 中为该 provider 注册 JSON 配置字段，让现有动态表单自动展示；不需要修改管理端前端页面。

## 2026-07-29：自适应 VAD 句尾

### 配置

当前 test 环境的 `VAD_SileroVAD`：

```yaml
min_silence_duration_ms: 550
incomplete_silence_duration_ms: 900
```

判定逻辑：

1. 默认按 550ms 尾部静音结束一句，降低普通短问句等待；
2. FunASR 2-pass online partial 若明显停在“请介绍一、帮我查一下、我想了解、关于、公司的”等缺少后续内容的片段，临时把本句阈值延长到 900ms；
3. 用户恢复说话后立即解除保护，最终完整句仍按 550ms 结束；
4. 非 2-pass ASR 或没有 partial 时保持普通阈值，不改变原 provider 行为；
5. 日志只记录 partial 长度及保护状态，不记录用户原文。

关键日志：

```text
LATENCY event=vad_partial_guard ... partial_len=4 base_ms=550 extended_ms=900
LATENCY event=vad_voice_stop ... silence_ms=597 target_ms=550 partial_guard=False
```

### 真实 ESP32 验收

- 固定 550ms 失败样例：“请介绍一下”后停顿约 0.6～0.7 秒，被提前提交为独立问题；
- 自适应版本压力测试：相同位置停顿约 0.7 秒，`vad_partial_guard` 成功触发，最终只产生一次完整 ASR final：`请介绍一下中科生创集团的临床应用中心`；
- 正常短问句实测句尾约 564～597ms，相比原 712～745ms 节省约 120～180ms；
- 同时将“一下”加入人名非实体词，避免不完整问题被误路由为姓名“一下”。

回滚方法：管理端将 `min_silence_duration_ms` 恢复为 `700`，删除 Redis 的 `server:config` 与 `model:data:VAD_SileroVAD` 两个精确缓存键，然后重启 `xiaozhi-esp32-server`。不得清空整个 Redis。

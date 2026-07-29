# VAD -> ASR -> LLM -> TTS 链路优化记录

## 当前结论

抛开模型推理速度，链路仍有优化空间，但不能盲目改默认阈值。

当前代码中 SileroVAD 默认配置：

```yaml
VAD:
  SileroVAD:
    min_silence_duration_ms: 200
```

200ms 已经是比较激进的尾部静音阈值。如果继续降低，容易误截断用户句子。因此本阶段先增加打点，不直接改默认 VAD 阈值。

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

如果现在直接把 `min_silence_duration_ms` 改得更低，可能短样例更快，但真实设备上会出现截断、半句话送 ASR、LLM 抢答等问题。

## 可优化方向

### 1. VAD 尾部策略

后续可做成分档：

| 场景 | silence threshold |
| --- | ---: |
| 短命令、短问答 | 200～300ms |
| 普通对话 | 300～500ms |
| 长句/手动模式 | 600ms 以上 |

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

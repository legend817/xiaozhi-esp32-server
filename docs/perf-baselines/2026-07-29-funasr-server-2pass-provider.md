# 2026-07-29 FunASRServer2Pass provider 验证

## 目的

新增 `fun_server_2pass` 旁路 ASR provider，用于验证 FunASR runtime 2-pass 能否在 xiaozhi 链路中边接收 PCM 边识别。

## 代码入口

- Provider：`main/xiaozhi-server/core/providers/asr/fun_server_2pass.py`
- YAML 示例：`main/xiaozhi-server/config.yaml` -> `ASR.FunASRServer2Pass`
- 管理端模型配置：`ASR_FunASRServer2Pass`

## 设计原则

- 保留原 `fun_server`，不破坏当前稳定 offline 链路。
- `fun_server_2pass` 从 VAD 检测到开始说话后建立 WebSocket。
- PCM 帧到达即转发给 FunASRServer。
- 缓存 `2pass-online` partial，仅用于日志和后续优化评估。
- 只用 `2pass-offline` final 触发 `handle_voice_stop` / LLM / TTS。

## Provider 级别探针

测试样例：

- 文件：`docs/perf-baselines/audio/ni_shi_shei.wav`
- 内容：`你是谁`
- FunASRServer：`wss://82.156.31.182:10095`
- mode：`2pass`

结果：

```text
LATENCY event=funasr_2pass_start trace=codex-2pass-probe uri=wss://82.156.31.182:10095 mode=2pass chunk_size=[5, 10, 5] interval=10
LATENCY event=funasr_2pass_partial trace=codex-2pass-probe ms=428 text_len=1 mode=2pass-online
LATENCY event=funasr_2pass_partial trace=codex-2pass-probe ms=504 text_len=1 mode=2pass-online
LATENCY event=funasr_2pass_final trace=codex-2pass-probe ms=734 text_len=4 mode=2pass-offline
```

探针输出：

```text
{'text': '你是谁。', 'ms': 797, 'frames': 21}
```

## 当前状态

- 新 provider 已通过语法检查。
- 新 provider 已进入 `xiaozhi-esp32-server:latency-dev` 镜像。
- 管理端数据库已新增 `ASR_FunASRServer2Pass`。
- `test` 智能体已切换到 `ASR_FunASRServer2Pass` 做真实 ESP32 验证。

## 真实 ESP32 验证与修复

### 2-pass 初始真实基线

测试设备：`10:b4:1d:e9:9c:30`

三句有效基线：

| 句子 | ASR final | LLM first token | TTS first audio | TTS 总结束 |
| --- | ---: | ---: | ---: | ---: |
| 你是谁 | 698ms | 1214ms | 1644ms | 8983ms |
| 现在几点 | 837ms | 1054ms | 1469ms | 7519ms |
| 讲个笑话 | 981ms | 624ms | 1065ms | 17810ms |

结论：

- 2-pass ASR 在真实设备上可用，final 通常在 0.7～1.0s。
- 体感瓶颈已转向 LLM 首 token、TTS 首包和长回复播报时长。

### 已做小修复

- `SileroVAD` 在同一轮语音中只记录一次 `vad_voice_stop`，避免重复刷屏污染统计。
- `fun_server_2pass` 在 `client_voice_stop` 后不再继续缓存/转发后续静音帧。
- `fun_server_2pass` 增加：
  - `funasr_2pass_stop_sent`
  - `funasr_2pass_final final_after_vad_stop_ms=...`
- `test` 智能体追加 `JOKE_SHORT_V1` 短笑话限制，要求讲笑话不超过 40 个汉字。

### 修复后抽样

`现在几点`：

```text
LATENCY event=vad_voice_stop trace=df160709943c silence_ms=773 speech_ms=1575
LATENCY event=funasr_2pass_stop_sent trace=df160709943c final_wait_started=true vad_to_stop_sent_ms=2
LATENCY event=funasr_2pass_final trace=df160709943c ms=1738 final_after_vad_stop_ms=163 text_len=4 mode=2pass-offline
LATENCY event=asr_end trace=df160709943c ms=0 text_len=4
LATENCY event=tts_first_audio trace=95c67d6916dc ms=1059
```

本次只出现一次 `vad_voice_stop`，修复有效。

### 注意

首次追加 `JOKE_SHORT_V1` 时因 MySQL CLI 字符集问题出现中文乱码，已用 `--default-character-set=utf8mb4` 修正。

## 后续验证

有 ESP32 后应做真实链路测试：

1. 将 test 智能体 ASR 切换到 `ASR_FunASRServer2Pass`。
2. 用真实设备说短句：`你是谁`、`现在几点`、`讲个笑话`。
3. 抓取日志：
   - `vad_first_voice`
   - `vad_voice_stop`
   - `funasr_2pass_partial`
   - `funasr_2pass_final`
   - `asr_start`
   - `asr_end`
   - `llm_stream_open`
   - `tts_first_audio`
4. 对比原 `ASR_FunASRServer`：
   - 从 `vad_voice_stop` 到 ASR final 的时间
   - 从 `vad_voice_stop` 到 TTS first audio 的时间
   - 完整播报结束时间

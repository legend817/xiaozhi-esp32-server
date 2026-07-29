# 2026-07-29 火山双流 TTS 短回答基线

## 范围

- 测试方式：无 ESP32 设备，容器内 WebSocket 文本模拟。
- 智能体：`test`
- Intent：`Intent_nointent`
- LLM：`LLM_AliLLM`，OpenAI 兼容接口，`Qwen3-30B-A3B`
- TTS：`TTS_HuoshanDoubleStreamTTS`
- 音色：`zh_female_wanwanxiaohe_moon_bigtts`
- 测试问题：`请只用八个字以内回答：你是谁`
- 运行次数：5

## 原始结果（完整打点复测）

| trace | llm_stream_open_ms | llm_first_token_ms | llm_total_ms | tts_first_audio_ms | tts_audio_total_ms | total_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 50f88bde34b2 | 630 | 718 | 824 | 1076 | 4458 | 5535 |
| 0883ae1327a2 | 141 | 495 | 530 | 911 | 3273 | 4185 |
| 0cd807287a9c | 146 | 463 | 513 | 878 | 2665 | 3544 |
| 0025cf53e457 | 142 | 510 | 531 | 854 | 2927 | 3782 |
| 256785476b04 | 148 | 482 | 503 | 794 | 2602 | 3397 |

## 汇总

| 指标 | P50 | P95/最大参考 |
| --- | ---: | ---: |
| LLM 建流 | 146ms | 630ms |
| LLM 首 token | 495ms | 718ms |
| LLM 完成 | 530ms | 824ms |
| TTS 首音频 | 878ms | 1076ms |
| TTS 首音频到结束 | 2927ms | 4458ms |
| 端到端完成 | 3782ms | 5535ms |

## 与豆包 HTTP 短回答基线对比

上一组 `TTS_DoubaoTTS` 短回答基线 P50：

| 指标 | 豆包 HTTP P50 | 火山双流 P50 | 变化 |
| --- | ---: | ---: | ---: |
| LLM 首 token | 495ms | 495ms | 持平 |
| LLM 完成 | 540ms | 530ms | 基本持平 |
| TTS 首音频 | 1318ms | 878ms | 约快 440ms |
| 端到端完成 | 5081ms | 3782ms | 约快 1299ms |

## 观察

- 本次提升主要来自 TTS：LLM 基本稳定，火山双流的首音频比豆包 HTTP 低约 33%。
- 第一跑仍有冷启动/连接建立波动，建议后续统计时区分 warm-up 与稳态。
- 双流 provider 不走普通分句打点路径，因此 `tts_first_segment_ms`、`tts_chars` 仍不适合直接与 HTTP 分句路径比较；本次已使用通用 `tts_audio_total_ms` 统计首音频到结束耗时。

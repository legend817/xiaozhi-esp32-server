# 2026-07-29 FunASRServer 并发基线

## 范围

- 测试对象：`ASR_FunASRServer`
- Provider：`fun_server`
- 协议：`wss://82.156.31.182:10095`
- 测试样例：`docs/perf-baselines/audio/ni_shi_shei.wav`
- PCM：16kHz、单声道、s16le，39056 bytes
- 每档并发轮数：2
- 并发档位：1、3、5、10

说明：本测试只测 ASR，不包含 LLM/TTS。

## 汇总

| 并发 | 请求数 | 成功 | 错误率 | P50 | P95 | 最小 | 最大 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2 | 2 | 0% | 531ms | 532ms | 530ms | 532ms |
| 3 | 6 | 6 | 0% | 630ms | 641ms | 623ms | 642ms |
| 5 | 10 | 10 | 0% | 592ms | 662ms | 516ms | 668ms |
| 10 | 20 | 20 | 0% | 965ms | 1166ms | 615ms | 1252ms |

## 观察

- 1～5 路并发很稳，P95 仍在 700ms 内。
- 10 路并发开始出现排队/抖动，P50 上升到约 965ms，P95 约 1166ms，但没有错误。
- 对比本地 `fun_local` 单路短音频 P50 约 956ms，FunASRServer 在 10 路并发下 P50 仍接近本地单路水平。

## 结论

当前 CPU FunASRServer 已经可以支撑至少 5 路短语音并发，10 路也可用但延迟明显上升。

是否需要 GPU/Triton 的判断：

- 如果目标并发小于 5 路，当前 CPU FunASRServer 暂时够用。
- 如果目标并发接近或超过 10 路，并且希望 ASR P95 低于 800ms，才需要继续评估 GPU FunASR 或 Triton。

## 下一步

1. 测 `LLM + TTS` 文本并发，确认 Qwen 和火山双流在多连接下的 P95。
2. 再测完整链路并发：`ASR -> LLM -> TTS`。


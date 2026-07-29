# 2026-07-29 FunASRServer 连通性与短链路基线

## 配置

- 智能体：`test`
- ASR：`ASR_FunASRServer`
- Provider：`fun_server`
- WebSocket：`wss://82.156.31.182:10095`
- SSL：开启

## 连通性排查

实测端口当前状态：

| 协议 | 结果 |
| --- | --- |
| `wss://82.156.31.182:10095` | 连接成功，握手约 219ms |
| `ws://82.156.31.182:10095` | 失败，返回非 HTTP 响应 |

因此 `ASR_FunASRServer.is_ssl` 应保持 `true`。

## Provider 直连识别

样例：`docs/perf-baselines/audio/ni_shi_shei.wav`

| run | ms | 识别结果 |
| --- | ---: | --- |
| 1 | 700 | 你是谁。 |
| 2 | 643 | 你是谁。 |
| 3 | 508 | 你是谁。 |

P50：`643ms`

## 完整链路

链路：`FunASRServer -> Qwen3-30B-A3B -> 火山双流 TTS`

| run | ASR ms | 识别结果 | LLM+TTS 完成 ms | 组合完成 ms |
| --- | ---: | --- | ---: | ---: |
| 1 | 560 | 你是谁。 | 7671 | 8231 |
| 2 | 535 | 你是谁。 | 8272 | 8807 |
| 3 | 541 | 你是谁。 | 5367 | 5909 |

P50：

| 指标 | P50 |
| --- | ---: |
| ASR | 541ms |
| LLM+TTS 完成 | 7671ms |
| 组合完成 | 8231ms |

## 对比本地 FunASR

同样 `ni_shi_shei.wav`，短答规则后本地 `fun_local` 复测：

| 指标 | fun_local P50 | fun_server P50 | 变化 |
| --- | ---: | ---: | ---: |
| ASR | 956ms | 541ms | 快约 415ms |
| 组合完成 | 8947ms | 8231ms | 快约 716ms |

## 结论

`ASR_FunASRServer` 已通，且当前短音频 ASR 明显快于本地 FunASR。后续应继续测并发和更真实的麦克风/ESP32 音频。


# 2026-07-29 本地 FunASR 基线

## 范围

- 测试对象：`ASR_FunASR`
- Provider：`fun_local`
- 模型目录：`models/SenseVoiceSmall`
- 测试音频：`models/SenseVoiceSmall/example/zh.mp3`
- 音频内容识别结果：`开饭时间早上9点至下午5点。`
- 原始音频时长：5.616s
- 转换后 PCM：16kHz、单声道、s16le，179,712 bytes
- 测试次数：5

## 模型裸推理基线

直接调用 FunASR `model.generate(input=mp3_path)`。

| run | ms |
| --- | ---: |
| 1 | 1839 |
| 2 | 990 |
| 3 | 1019 |
| 4 | 1048 |
| 5 | 1185 |

汇总：

| 指标 | 值 |
| --- | ---: |
| 模型加载 | 7872ms |
| P50 | 1048ms |
| 平均 | 1216ms |
| 最小 | 990ms |
| 最大 | 1839ms |

## 项目 provider 标准入口基线

通过 `ASRProvider.speech_to_text_wrapper([pcm], session_id)` 调用，和项目实际 PCM 输入路径一致。

| run | funasr_generate_ms | wrapper_ms | text_len |
| --- | ---: | ---: | ---: |
| 1 | 1779 | 1781 | 14 |
| 2 | 1912 | 1913 | 14 |
| 3 | 1755 | 1757 | 14 |
| 4 | 1872 | 1873 | 14 |
| 5 | 1869 | 1870 | 14 |

汇总：

| 指标 | 值 |
| --- | ---: |
| Provider 加载 | 3889ms |
| P50 | 1870ms |
| 平均 | 1839ms |
| 最小 | 1757ms |
| 最大 | 1913ms |
| RTF 参考 | 约 0.27～0.30 |

## 观察

- 当前本地 FunASR 热态识别 5.6s 语音，项目标准入口 P50 约 1.87s。
- 相比当前文本链路，ASR 是明显成本项：火山双流 TTS 首音频 P50 约 878ms，LLM 首 token P50 约 495ms，而 FunASR P50 约 1870ms。
- 这说明真实语音链路如果要继续降延迟，ASR 是下一阶段重点。
- 裸 mp3 路径比 PCM bytes 路径快，后续需要确认 FunASR 对 raw bytes 输入是否存在额外处理或格式推断开销。

## 后续建议

1. 补完整语音链路测试：`PCM -> FunASR -> LLM -> 火山双流 TTS`。
2. 单独部署 FunASR runtime server 后，对比 `fun_local` 与 `fun_server`：
   - ASR 总耗时
   - 并发 5/10 路 P95
   - Python 主进程 CPU 占用和阻塞情况
3. 如果追求更低首字延迟，优先评估流式 ASR，而不是继续优化批量 FunASR。


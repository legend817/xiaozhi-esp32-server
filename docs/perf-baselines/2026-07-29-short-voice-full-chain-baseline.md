# 2026-07-29 短语音完整链路基线

## 范围

- 测试方式：无 ESP32 设备，容器内生成短语音样例，然后串联服务端核心链路。
- 语音样例来源：当前 test 智能体的 `TTS_HuoshanDoubleStreamTTS` 生成 PCM，再封装为 WAV。
- ASR：`ASR_FunASR` / `fun_local`
- LLM：`LLM_AliLLM` / `Qwen3-30B-A3B`
- Intent：`Intent_nointent`
- TTS：`TTS_HuoshanDoubleStreamTTS`
- 每条样例测试次数：3

样例文件：

- `docs/perf-baselines/audio/ni_shi_shei.wav`
- `docs/perf-baselines/audio/xian_zai_ji_dian.wav`
- `docs/perf-baselines/audio/jiang_xiao_hua_20.wav`

说明：这是合成语音样例，不等同于真人麦克风输入。它适合做服务端链路回归基线，但最终仍需要 ESP32 或真人录音复测。

## 样例生成结果

| sample | 文本 | PCM bytes | 生成耗时 |
| --- | --- | ---: | ---: |
| `ni_shi_shei` | 你是谁 | 39056 | 636ms |
| `xian_zai_ji_dian` | 现在几点 | 32930 | 622ms |
| `jiang_xiao_hua_20` | 二十字以内讲个笑话 | 56212 | 741ms |

## 原始结果

| sample | run | ASR ms | ASR 结果 | LLM+TTS 完成 ms | 组合完成 ms |
| --- | ---: | ---: | --- | ---: | ---: |
| `ni_shi_shei` | 1 | 941 | 你是谁？ | 16416 | 17357 |
| `ni_shi_shei` | 2 | 891 | 你是谁？ | 15887 | 16778 |
| `ni_shi_shei` | 3 | 910 | 你是谁？ | 12169 | 13078 |
| `xian_zai_ji_dian` | 1 | 4963 | . | 10897 | 15860 |
| `xian_zai_ji_dian` | 2 | 4995 | . | 12845 | 17840 |
| `xian_zai_ji_dian` | 3 | 5011 | . | 10792 | 15803 |
| `jiang_xiao_hua_20` | 1 | 1102 | 20字以内讲的笑话。 | 8770 | 9871 |
| `jiang_xiao_hua_20` | 2 | 916 | 20字以内讲的笑话。 | 5873 | 6789 |
| `jiang_xiao_hua_20` | 3 | 1035 | 20字以内讲的笑话。 | 14103 | 15137 |

## 拆分指标

| sample | run | LLM 首 token | LLM 完成 | TTS 首音频 | TTS 首音频到结束 | 说完到首音频 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ni_shi_shei` | 1 | 542 | 926 | 994 | 15263 | 1935 |
| `ni_shi_shei` | 2 | 494 | 907 | 745 | 14990 | 1636 |
| `ni_shi_shei` | 3 | 658 | 747 | 1071 | 10936 | 1981 |
| `xian_zai_ji_dian` | 1 | 535 | 797 | 882 | 9854 | 5845 |
| `xian_zai_ji_dian` | 2 | 537 | 932 | 827 | 11869 | 5822 |
| `xian_zai_ji_dian` | 3 | 508 | 787 | 869 | 9776 | 5880 |
| `jiang_xiao_hua_20` | 1 | 451 | 685 | 727 | 7868 | 1829 |
| `jiang_xiao_hua_20` | 2 | 547 | 629 | 960 | 4756 | 1876 |
| `jiang_xiao_hua_20` | 3 | 440 | 871 | 897 | 13031 | 1932 |

`说完到首音频 = ASR ms + TTS 首音频 ms`。

## P50 汇总

| sample | ASR P50 | LLM 首 token P50 | TTS 首音频 P50 | 说完到首音频 P50 | 组合完成 P50 | 有效性 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ni_shi_shei` | 910ms | 542ms | 994ms | 1935ms | 16778ms | 有效 |
| `xian_zai_ji_dian` | 4995ms | 535ms | 869ms | 5845ms | 15860ms | 无效，ASR 识别成 `.` |
| `jiang_xiao_hua_20` | 1035ms | 451ms | 897ms | 1876ms | 9871ms | 基本有效，ASR 文本有轻微偏差 |

## 观察

- 对有效样例，当前短语音“说完到首音频”P50 约 1.9s。
- `ni_shi_shei` 和 `jiang_xiao_hua_20` 的 ASR 热态耗时约 0.9～1.0s，比 5.6s 长音频的 1.8s 明显低。
- `xian_zai_ji_dian` 合成音被 FunASR 稳定识别为 `.`，不适合作为有效样例。这说明合成测试集需要先做 ASR 可用性筛选。
- 组合完成时间仍主要受回答长度影响；例如 `ni_shi_shei` 虽是短问题，但智能体回答较长，导致播放完成 P50 仍超过 16s。

## 结论

当前可用短语音样例下，服务端核心链路首响应大致为：

```text
ASR 0.9～1.0s + LLM/TTS 到首音频 0.9～1.0s = 说完到首音频约 1.9s
```

如果要继续接近官方服务器体感，下一阶段重点不是火山 TTS，而是：

1. ASR 从批量识别改成流式识别，降低“说完后才开始识别”的等待。
2. 约束回答长度，避免短问长答导致 TTS 播放时间过长。
3. 增加真实麦克风/ESP32 音频样例，替代合成语音样例。

## 短问短答规则后复测

已对 test 智能体追加 `SHORT_REPLY_OPTIMIZATION_V1` 规则，要求短问题不超过 15 个汉字，普通问题默认 1～2 句。

复测样例：`ni_shi_shei.wav`

| run | ASR ms | LLM 首 token | LLM 完成 | TTS 首音频 | TTS 首音频到结束 | 组合完成 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1768 | 1164 | 1309 | 1670 | 4824 | 9258 |
| 2 | 956 | 608 | 690 | 1025 | 6807 | 8947 |
| 3 | 912 | 514 | 604 | 910 | 4330 | 6322 |

P50 对比：

| 指标 | 优化前 | 优化后 | 变化 |
| --- | ---: | ---: | ---: |
| ASR | 910ms | 956ms | 基本持平 |
| TTS 首音频 | 994ms | 1025ms | 基本持平 |
| TTS 首音频到结束 | 14990ms | 4824ms | 明显下降 |
| 组合完成 | 16778ms | 8947ms | 约快 7831ms |

结论：短答规则主要降低 TTS 播放总时长，对“首音频”影响不大，但对短问短答体感明显有效。

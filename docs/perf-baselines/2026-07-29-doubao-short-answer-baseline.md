# 2026-07-29 DoubaoTTS short-answer baseline

## Scope

- Test type: no ESP32, WebSocket `listen/detect` text simulation.
- Device: `codex-latency-test` local test device.
- Agent: `test`.
- Intent: `Intent_nointent`.
- LLM: `LLM_AliLLM`, OpenAI-compatible `Qwen3-30B-A3B`.
- TTS: `TTS_DoubaoTTS`.
- Query: `请只用八个字以内回答：你是谁`.
- Runs: 5.
- Server image: `xiaozhi-esp32-server:latency-dev`.

This is the comparison baseline before switching to Volcano bidirectional
streaming TTS.

## Raw Results

| Trace | LLM stream open | LLM first token | LLM total | TTS first segment | First segment chars | TTS first audio | TTS chars | TTS total | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `a47c89a3a9da` | 575 ms | 959 ms | 989 ms | 962 ms | 4 | 1777 ms | 10 | 4118 ms | 5081 ms |
| `bc4401840331` | 153 ms | 462 ms | 522 ms | 489 ms | 6 | 1198 ms | 11 | 3127 ms | 3616 ms |
| `1b9bdedf194e` | 151 ms | 481 ms | 552 ms | 486 ms | 6 | 1318 ms | 17 | 5150 ms | 5636 ms |
| `24f0844b0406` | 142 ms | 532 ms | 540 ms | 540 ms | 4 | 1263 ms | 9 | 3580 ms | 4120 ms |
| `64f5a95da717` | 142 ms | 495 ms | 526 ms | 500 ms | 4 | 1329 ms | 15 | 5122 ms | 5623 ms |

## Summary

| Metric | P50 | P95 |
| --- | ---: | ---: |
| LLM stream open | 151 ms | 575 ms |
| LLM first token | 495 ms | 959 ms |
| LLM total | 540 ms | 989 ms |
| TTS first segment | 500 ms | 962 ms |
| First segment chars | 4 | 6 |
| TTS first audio | 1318 ms | 1777 ms |
| TTS chars | 11 | 17 |
| TTS total | 4118 ms | 5150 ms |
| Total | 5081 ms | 5636 ms |

## Observations

- `Intent_nointent` remains active and logs show `tools=false`.
- For short answers, LLM first token P50 is about 0.5 seconds.
- DoubaoTTS first audio P50 is about 1.3 seconds.
- Even for 9-17 output chars, non-bidirectional TTS total time is 3.1-5.2 seconds.
- This is the clean baseline to compare against Volcano bidirectional streaming
  TTS and later Triton/CosyVoice.

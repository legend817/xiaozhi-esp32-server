# 2026-07-29 nointent text baseline

## Scope

- Test type: no ESP32, WebSocket `listen/detect` text simulation.
- Device: `codex-latency-test` local test device.
- Agent: `test`.
- Intent: `Intent_nointent`.
- LLM: `LLM_AliLLM`, OpenAI-compatible `Qwen3-30B-A3B`.
- TTS: `TTS_DoubaoTTS`.
- Prompt: current `test` agent prompt from manager-api.
- Query: `你好，请用一句话介绍你自己`.
- Runs: 5.
- Server image: `xiaozhi-esp32-server:latency-dev`.

This baseline excludes the earlier warm-up run at `08:59:02`.

## Raw Results

| Trace | LLM stream open | LLM first token | LLM total | TTS first segment | TTS first audio | TTS total | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ec1aa89b6e30` | 143 ms | 532 ms | 899 ms | 537 ms | 1465 ms | 14857 ms | 15395 ms |
| `e32d12e1e879` | 147 ms | 477 ms | 726 ms | 525 ms | 1517 ms | 10555 ms | 11081 ms |
| `e0469ad81ec2` | 150 ms | 458 ms | 748 ms | 498 ms | 1319 ms | 11032 ms | 11531 ms |
| `972521bc5cb6` | 141 ms | 541 ms | 725 ms | 549 ms | 1998 ms | 11855 ms | 12404 ms |
| `ed96cf1ad7c2` | 139 ms | 494 ms | 683 ms | 501 ms | 1570 ms | 9504 ms | 10005 ms |

## Summary

| Metric | P50 | P95 |
| --- | ---: | ---: |
| LLM stream open | 143 ms | 150 ms |
| LLM first token | 494 ms | 541 ms |
| LLM total | 726 ms | 899 ms |
| TTS first segment | 525 ms | 549 ms |
| TTS first audio | 1517 ms | 1998 ms |
| TTS total | 11032 ms | 14857 ms |
| Total | 11531 ms | 15395 ms |

## Observations

- `Intent_nointent` correctly disables OpenAI tools: logs show `tools=false`.
- LLM first token is not the current bottleneck for normal text chat.
- TTS first audio is around 1.3-2.0 seconds.
- Total latency is dominated by TTS generation/playout of the full answer.
- The generated answer varies in length across runs, so total latency should be
  compared together with output text length.

## Next Checks

- Add output character count to the final `tts_end` summary.
- Run a short-answer prompt designed to produce one fixed sentence.
- Run a TTS-only benchmark against DoubaoTTS with fixed text.
- Then compare Volcano bidirectional streaming TTS and Triton/CosyVoice.

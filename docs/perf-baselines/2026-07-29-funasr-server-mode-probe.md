# 2026-07-29 FunASRServer mode 探测

## 目的

确认当前 FunASRServer 是不是 2-pass，以及 xiaozhi 当前 provider 实际是否利用了流式 partial。

## 结论

- 服务端确实返回 `2pass-online` / `2pass-offline` 结果，说明 runtime 支持 2-pass。
- 但当前项目 `core/providers/asr/fun_server.py` 发送的是 `mode: offline`，并且一次性发送整段 PCM。
- 因此当前主链路虽然连接的是 2-pass runtime，但没有利用边说边识别的 partial；它仍是“说完后整段提交，等待 final”。

## 当前 provider 实际请求

```json
{
  "mode": "offline",
  "chunk_size": [5, 10, 5],
  "chunk_interval": 10,
  "is_speaking": true
}
```

## 测试样例

- 样例：`docs/perf-baselines/audio/ni_shi_shei.wav`
- PCM：16kHz、单声道、s16le，39056 bytes
- 内容：`你是谁`

## mode 对比

### 收到 final 立即结束

| mode | 发送方式 | 首个返回 | final | 返回消息 |
| --- | --- | ---: | ---: | --- |
| `offline` | 一次性发送整段 PCM | 515ms | 515ms | `2pass-offline: 你是谁。` |
| `online` | 快速分帧发送 | 389ms | 550ms | `2pass-online: 你`、`2pass-online: 是`、`2pass-offline: 你是谁` |
| `2pass` | 快速分帧发送 | 474ms | 803ms | `2pass-online: 你`、`2pass-online: 是`、`2pass-offline: 你是谁。` |
| `2pass` | 实时 60ms 分帧 | 937ms | 1810ms | `2pass-online: 你`、`2pass-online: 是`、`2pass-offline: 你是谁。` |

## 解读

- `offline` 也返回 `2pass-offline`，所以用户看到 “2-pass” 是对的。
- 当前项目 provider 使用 `offline`，所以它只能得到最终文本，不能提前利用 `2pass-online` partial。
- `2pass` 实时分帧时，首个 partial 在开始后约 937ms 出现，final 在 1810ms 出现。这个 final 是从开始说话计时，不是从说完后计时。
- 对真实设备来说，如果音频边说边发，用户说完时 final 可能已经接近可用；这才是 2-pass 的体感收益。

## 下一步建议

新增旁路 provider，例如 `fun_server_2pass.py`：

1. WebSocket 在会话开始时打开。
2. 设备音频帧到达时立即转发给 FunASRServer。
3. 缓存 `2pass-online` partial，但不直接触发 LLM。
4. 收到 `2pass-offline` final 或 VAD stop 后，触发 `handle_voice_stop` / `startToChat`。
5. 保留现有 `fun_server` provider 作为稳定 offline 回退。

## 执行状态

已新增 `core/providers/asr/fun_server_2pass.py`，并注册管理端模型 `ASR_FunASRServer2Pass`。

初始 provider 探针记录见：

- `docs/perf-baselines/2026-07-29-funasr-server-2pass-provider.md`

# Triton CosyVoice2 服务端流式优化记录

> 音色添加、智控台配置和在线试听流程见 [Triton CosyVoice 音色指南](./triton-cosyvoice-voice-guide.md)。

## 变更信息

- 变更日期：2026-08-06
- 远端目录：`~/CosyVoice/runtime/triton_trtllm`
- Compose 文件：`docker-compose.cosyvoice2.unet.yml`
- Compose 服务：`tts`
- Triton 模型：`cosyvoice2`
- 修改文件：`model_repo/cosyvoice2/1/model.py`
- 原始备份：`model_repo/cosyvoice2/1/model.py.codex-backup-20260806`
- xiaozhi-server Provider 提交：`71a96b60`

本次没有修改模型权重、声纹数据、Compose 配置、manager-api 或
manager-web。密码等登录凭据未写入仓库。

## 服务端代码改动

### 默认音色切换为湾湾小何

模型目录中的 `spk2info.pt` 已包含缓存键 `xiaohe`：

- 名称：湾湾小何
- 缓存键：`xiaohe`
- 参考文本：`今天天气真是太好了，阳光灿烂心情超级棒`

默认请求不传 `reference_wav` 时，编排模型负责读取提示文本和 speech token，
token2wav 负责读取 speech feat 和 speaker embedding，因此两处必须使用同一个
缓存键：

```diff
# model_repo/cosyvoice2/1/model.py
-        self.default_spk_info = spk_info["001"]
+        self.default_spk_info = spk_info["xiaohe"]

# model_repo/token2wav/1/model.py
-        self.default_spk_info = spk_info["001"]
+        self.default_spk_info = spk_info["xiaohe"]
```

切换前的模板备份为：

- `model_repo/cosyvoice2/1/model.py.codex-backup-before-xiaohe-20260806`
- `model_repo/token2wav/1/model.py.codex-backup-before-xiaohe-20260806`

重启后已确认生成目录中的两个模型均加载 `xiaohe`。默认请求生成了 10 个
waveform chunk、5.52 秒 24kHz 单声道音频；四个 Python 实例预热完成后的
localhost 首块延迟恢复到约 200ms。

### 1. 缩短首个音频块等待时间

```diff
-        self.token_hop_len = 15
+        self.token_hop_len = 8
```

首轮 token2wav 从等待 `15 + 3 lookahead` 个 semantic token，调整为等待
`8 + 3 lookahead` 个 token，使第一个 waveform chunk 更早返回。

### 2. 缩短 semantic token 轮询间隔

```diff
-                        time.sleep(0.02)
+                        time.sleep(0.005)
```

等待 LLM token 时的检查周期由 20ms 降为 5ms，减少 token 已满足首块条件后
的额外等待。

### 3. 使用小块且有上限的后续 chunk

原实现首块后按 `25、50、100...` token 增长：

```diff
-                            this_token_hop_len = self.token_frame_rate * (2 ** chunk_index)
+                            this_token_hop_len = min(
+                                self.token_hop_len * (2 ** chunk_index),
+                                self.token_hop_len * 2,
+                            )
```

修改后的 hop 序列为 `8 → 8 → 16 → 16...`。第二块可以更早补充播放
缓冲，后续块最多 16 token，避免下一块阈值过大而迟迟无法发送。

### 4. LLM 完成后继续排空已生成 token

原实现只要 LLM 标记完成就立即退出流式循环。此时即使内存里已经积压大量
semantic token，也会留到最后一次 token2wav 统一处理，造成尾段播放空洞。

```diff
-                    if llm_is_done_flag[0]:
+                    if (
+                        llm_is_done_flag[0]
+                        and pending_num
+                        < this_token_hop_len + self.flow_pre_lookahead_len
+                    ):
                         break
```

现在只有在 LLM 已完成且剩余 token 不足一个流式块时才退出；已积压的完整块
仍会立即通过 decoupled response 发送。

## 加载变更

`run.sh` 会从 `model_repo/cosyvoice2` 重新生成 `model_repo_cosyvoice2`，因此
必须修改上述源模板，而不是只改生成目录。加载命令：

```bash
cd ~/CosyVoice/runtime/triton_trtllm
sudo docker compose -f docker-compose.cosyvoice2.unet.yml restart tts
```

服务完整加载约需 2 分钟。确认外部 HTTP 健康端点返回 200 后再测试：

```bash
curl http://127.0.0.1:8000/v2/health/ready
```

确认生成后的运行文件参数：

```bash
grep -nE 'token_hop_len =|time.sleep|self.token_hop_len \*' \
  model_repo_cosyvoice2/cosyvoice2/1/model.py
```

## 实测结果

测试文本：

> 你好，我是小智，很高兴为你服务。今天我们来测试语音合成的响应速度。

测试方式为 Triton gRPC `start_stream` / `async_stream_infer`，使用服务端默认
音色。服务配置了 4 个 CosyVoice Python 实例，正式采样前需要至少覆盖四个
实例进行预热。

| 指标 | 原始配置 | 优化后 | 变化 |
| --- | ---: | ---: | ---: |
| 热态首块中位数 | 386.1ms | 351.3ms | -34.8ms（约 9%） |
| 热态首块 P95 | 450.0ms | 399.5ms | -50.5ms（约 11%） |
| 完整生成中位数 | 1881.3ms | 2043.2ms | +161.9ms |
| waveform chunk 数 | 约 4 | 约 13–14 | 更细粒度流式输出 |

连续播放探针进行了三次采样：第二块到达时的最小剩余播放缓冲约 42.5ms，
所有 chunk 的缓冲余量均为非负，原先句尾约 0.3–0.5 秒的空洞已消除。

该调整优先优化用户感知的首包和播放连续性，因此接受完整生成耗时小幅增加。
PCM waveform chunk 由 xiaozhi-server 收到后立即编码为 Opus 帧发送给 ESP32，
不会在服务端重新拼接完整 WAV。

## 回退方式

只回退默认音色、保留流式优化：

```bash
cd ~/CosyVoice/runtime/triton_trtllm
cp model_repo/cosyvoice2/1/model.py.codex-backup-before-xiaohe-20260806 \
  model_repo/cosyvoice2/1/model.py
cp model_repo/token2wav/1/model.py.codex-backup-before-xiaohe-20260806 \
  model_repo/token2wav/1/model.py
sudo docker compose -f docker-compose.cosyvoice2.unet.yml restart tts
```

如发现音质、并发能力或播放稳定性异常，可恢复备份并重启：

```bash
cd ~/CosyVoice/runtime/triton_trtllm
cp model_repo/cosyvoice2/1/model.py.codex-backup-20260806 \
  model_repo/cosyvoice2/1/model.py
sudo docker compose -f docker-compose.cosyvoice2.unet.yml restart tts
```

回退后再次检查健康端点和生成目录中的参数。不要只恢复
`model_repo_cosyvoice2`，因为下次执行 `run.sh` 时该目录会被重新生成。

## 后续建议

- 服务每次重启后对 4 个 Python 实例分别执行一次预热请求，避免前四位用户
  命中冷实例。
- 如实际并发很低，可单独压测 `cosyvoice2` 的实例数 1 与实例数 4；减少实例数
  可能改善冷启动和延迟波动，但会降低并发能力，不能直接在线上修改。
- 优化 TensorRT-LLM engine 或 token2wav engine 前应保存相同文本、相同音色和
  相同预热条件下的基线，并同时检查首块延迟、完整耗时和播放缓冲余量。

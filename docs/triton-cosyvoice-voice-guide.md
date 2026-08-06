# Triton CosyVoice 音色添加与试听指南

本文记录 Triton CosyVoice2 自部署服务新增音色的完整流程，包括服务端
`spk2info.pt` 缓存音色、智控台音色配置、在线试听和后续的多音色切换支持。

## 适用环境

- 服务端：`lin@82.156.31.182 -p 14122`
- CosyVoice 路径：`/home/lin/CosyVoice/runtime/triton_trtllm`
- 模型目录：`/home/lin/CosyVoice/runtime/triton_trtllm/CosyVoice2-0.5B`
- Triton 容器：`triton_trtllm-tts-1`
- Compose 文件：`docker-compose.cosyvoice2.unet.yml`

当前 `spk2info.pt` 已包含：

```text
001
longxiaoxia
xiaohe
```

当前 Triton 默认使用 `xiaohe`。

## 一、服务端添加 spk2info 缓存音色

### 1. 准备参考音频

参考音频必须是：

- 16kHz
- 单声道
- 16-bit PCM WAV

示例路径：

```text
/home/lin/CosyVoice/runtime/triton_trtllm/my_voice_16k.wav
```

### 2. 执行添加脚本

SSH 到服务端后执行：

```bash
cd /home/lin/CosyVoice

PYTHONPATH=/home/lin/CosyVoice \
/home/lin/CosyVoice/runtime/triton_trtllm/.venv/bin/python - <<'PY'
from cosyvoice.cli.cosyvoice import CosyVoice2

model_dir = '/home/lin/CosyVoice/runtime/triton_trtllm/CosyVoice2-0.5B'

cosyvoice = CosyVoice2(
    model_dir,
    load_jit=False,
    load_trt=False,
    fp16=False,
)

cosyvoice.add_zero_shot_spk(
    prompt_text='今天天气真是太好了，阳光灿烂心情超级棒',
    prompt_wav='/home/lin/CosyVoice/runtime/triton_trtllm/my_voice_16k.wav',
    zero_shot_spk_id='my_voice',
)

cosyvoice.save_spkinfo()
print(cosyvoice.list_available_spks())
PY
```

`zero_shot_spk_id` 是音色编码，之后智控台的 `tts_voice` 字段要填同一个值。

### 3. 验证写入结果

```bash
cd /home/lin/CosyVoice/runtime/triton_trtllm

.venv/bin/python -c "import torch; d=torch.load('CosyVoice2-0.5B/spk2info.pt', map_location='cpu', weights_only=False); print(list(d.keys()))"
```

输出中应能看到新音色 key。

### 4. 重启 Triton 服务

```bash
cd /home/lin/CosyVoice/runtime/triton_trtllm
sudo docker compose -f docker-compose.cosyvoice2.unet.yml restart tts
```

完整加载约需 2 分钟，健康检查：

```bash
curl http://127.0.0.1:8000/v2/health/ready
```

## 二、智控台新增音色

1. 打开智控台。
2. 进入 `模型配置` → `语音合成`。
3. 找到 `TTS_TritonCosyVoiceTTS`，点击“音色管理”。
4. 点击“新增”，填写：
   - `音色编码`：服务端 `spk2info.pt` 的 key，例如 `my_voice`
   - `音色名称`：前端展示名称
   - `语言类型`：例如 `普通话`
   - `试听音频地址`：可访问的 mp3/wav URL
   - `备注`：按需填写
   - `排序`：按需填写
5. 保存。
6. 进入 `智能体管理` → 选择智能体 → `配置角色`。
7. TTS 选择 `TTS_TritonCosyVoiceTTS`，音色下拉选择新增音色。
8. 保存。

等价 SQL：

```sql
INSERT INTO ai_tts_voice (
  id, tts_model_id, name, tts_voice, languages, voice_demo,
  remark, sort, creator, create_date, update_date
) VALUES (
  'TTS_TritonCosyVoiceTTS_0003',
  'TTS_TritonCosyVoiceTTS',
  '我的新音色',
  'my_voice',
  '普通话',
  'https://example.com/my_voice.mp3',
  'CosyVoice spk2info 缓存音色',
  3,
  1,
  NOW(),
  NOW()
);
```

### 配置缓存

修改数据库或智控台音色后，执行：

```bash
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB

docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

## 三、在线试听

火山音色的在线试听本质上是 `ai_tts_voice.voice_demo` 保存了一个可播放的音频
URL。Triton CosyVoice 同样复用该字段，不需要单独开发试听接口。

`voice_demo` 支持：

- 公网 HTTP/HTTPS URL
- 可通过智控台访问的静态资源 URL

只填写 `voice_demo` 后，角色配置页面会出现播放按钮。

## 四、参考音频音色

如果暂时不改 Triton 模型，也可以给每个音色配置参考音频：

- `reference_audio`：16kHz 16-bit PCM WAV，路径必须能被
  `xiaozhi-esp32-server` 容器读取，例如挂载到
  `/opt/xiaozhi-esp32-server/data/voices/my_voice.wav`
- `reference_text`：参考音频对应的文本

这种方式每次请求都会重新提取音频特征和说话人 embedding，速度比
`spk2info.pt` 缓存音色慢。

## 五、支持多个缓存音色切换

当前 Triton 模型在没有 `reference_wav` 时固定使用默认缓存音色，不会根据
前端选择的音色编码切换。要让 `spk2info.pt` 中多个音色都能被选择，还需要：

1. 在 Triton `config.pbtxt` 增加可选输入 `spk_id`。
2. 在 `model.py` 中当未传 `reference_wav` 时，根据 `spk_id` 读取
   `spk_info[spk_id]`，未传则使用默认音色。
3. 在 xiaozhi `core/providers/tts/triton_cosyvoice.py` 的
   `_build_inputs()` 中把 `voice` 作为 `spk_id` 传给 Triton。
4. 重启 Triton 服务和 xiaozhi server。

实现后，每个 `ai_tts_voice` 行的 `tts_voice` 直接填 `spk2info.pt` 的 key，
即可在前端选择并切换到对应缓存音色。

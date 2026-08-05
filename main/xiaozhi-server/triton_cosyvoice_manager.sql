-- 可选：仅当需要在 manager-web 页面配置 Triton CosyVoice2 时手工执行。
-- 此文件不由 manager-api/Liquibase 自动加载。

DELETE FROM `ai_model_provider` WHERE `id` = 'SYSTEM_TTS_TritonCosyVoiceTTS';
INSERT INTO `ai_model_provider`
(`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES (
  'SYSTEM_TTS_TritonCosyVoiceTTS',
  'TTS',
  'triton_cosyvoice',
  'Triton CosyVoice2（流式）',
  '[
    {"key":"server","label":"Triton gRPC地址","type":"string"},
    {"key":"model_name","label":"模型名称","type":"string"},
    {"key":"model_version","label":"模型版本（可选）","type":"string"},
    {"key":"sample_rate","label":"输出采样率","type":"number"},
    {"key":"reference_audio","label":"参考音频路径（可选）","type":"string"},
    {"key":"reference_text","label":"参考音频文本（可选）","type":"string"},
    {"key":"voice","label":"音色缓存标识","type":"string"},
    {"key":"request_timeout","label":"请求超时（秒）","type":"number"},
    {"key":"ssl","label":"启用 gRPC TLS","type":"boolean"}
  ]',
  24,
  1,
  NOW(),
  1,
  NOW()
);

DELETE FROM `ai_model_config` WHERE `id` = 'TTS_TritonCosyVoiceTTS';
INSERT INTO `ai_model_config`
VALUES (
  'TTS_TritonCosyVoiceTTS',
  'TTS',
  'TritonCosyVoiceTTS',
  'Triton CosyVoice2（流式）',
  0,
  1,
  '{
    "type":"triton_cosyvoice",
    "server":"82.156.31.182:28001",
    "model_name":"cosyvoice2",
    "model_version":"",
    "sample_rate":24000,
    "reference_audio":"",
    "reference_text":"",
    "voice":"triton_cosyvoice",
    "request_timeout":30,
    "ssl":false
  }',
  'https://github.com/legend817/CosyVoice/blob/main/runtime/triton_trtllm/client_grpc.py',
  'Triton CosyVoice2 流式 TTS：server 填 gRPC 地址且不含协议；模型须启用 decoupled transaction policy；reference_audio 可留空使用服务端默认音色。',
  24,
  NULL,
  NULL,
  NULL,
  NULL
);

-- 智能体页面要求 TTS 至少有一个可选音色，此记录代表服务端默认音色。
DELETE FROM `ai_tts_voice` WHERE `id` = 'TTS_TritonCosyVoiceTTS_0001';
INSERT INTO `ai_tts_voice`
(`id`, `tts_model_id`, `name`, `tts_voice`, `languages`, `voice_demo`, `remark`, `reference_audio`, `reference_text`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES (
  'TTS_TritonCosyVoiceTTS_0001',
  'TTS_TritonCosyVoiceTTS',
  '服务端默认音色',
  'triton_cosyvoice',
  '普通话',
  NULL,
  '使用模型配置中的参考音频；参考音频留空时使用 Triton 服务端默认音色',
  NULL,
  NULL,
  1,
  1,
  NOW(),
  1,
  NOW()
);

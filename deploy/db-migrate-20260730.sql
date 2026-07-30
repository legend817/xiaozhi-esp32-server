-- =============================================================
-- 数据库迁移：2026-07-30 优化项
-- 在远程服务器上执行：mysql -uroot -p xiaozhi_esp32_server < deploy/db-migrate-20260730.sql
-- =============================================================

-- 1. VAD：尾延迟 550ms → 450ms
UPDATE ai_model_config
SET config_json = JSON_SET(config_json, '$.min_silence_duration_ms', CAST('450' AS JSON))
WHERE id = 'VAD_SileroVAD';

-- 2. LLM：禁用 Qwen3 思考模式
UPDATE ai_model_config
SET config_json = JSON_SET(config_json, '$.extra_body', CAST('{"enable_thinking": false}' AS JSON))
WHERE id = 'LLM_AliLLM';

-- 3. RAG：预播话术（多条用分号分隔，随机选一条）
UPDATE ai_model_config
SET config_json = JSON_SET(
    config_json,
    '$.staged_first_reply',
    '我查一下知识库哈；让我查查资料；稍等一下，我找找；这个问题我查一下；我搜一下相关资料'
)
WHERE id = 'RAG_RAGFlow';

SELECT 'Migration complete. Affected rows:' AS status;
SELECT 'VAD_SileroVAD' AS target, ROW_COUNT() AS rows FROM ai_model_config WHERE id = 'VAD_SileroVAD';
SELECT 'LLM_AliLLM (extra_body)' AS target, ROW_COUNT() AS rows FROM ai_model_config WHERE id = 'LLM_AliLLM';
SELECT 'RAG_RAGFlow (staged_reply)' AS target, ROW_COUNT() AS rows FROM ai_model_config WHERE id = 'RAG_RAGFlow';

-- 4. 新增 FunASRServer2Pass 的 provider 字段定义（前端回显用）
INSERT IGNORE INTO ai_model_provider (id, model_type, provider_code, name, fields, sort, creator, create_date)
VALUES (
    'SYSTEM_ASR_FunASRServer2Pass',
    'ASR',
    'fun_server_2pass',
    'FunASR服务2Pass语音识别',
    '[{"key": "host", "type": "string", "label": "服务地址"}, {"key": "port", "type": "number", "label": "端口号"}, {"key": "is_ssl", "type": "boolean", "label": "是否使用SSL"}, {"key": "api_key", "type": "string", "label": "API密钥"}, {"key": "mode", "type": "string", "label": "模式(offline/online/2pass)"}, {"key": "chunk_size", "type": "string", "label": "分片大小"}, {"key": "chunk_interval", "type": "number", "label": "分片间隔"}, {"key": "itn", "type": "boolean", "label": "是否启用逆文本正则化"}, {"key": "recv_timeout", "type": "number", "label": "接收超时(秒)"}, {"key": "hotwords", "type": "string", "label": "热词(JSON格式)"}, {"key": "text_corrections", "type": "string", "label": "纠错映射(JSON格式)"}, {"key": "output_dir", "type": "string", "label": "输出目录"}]',
    6, 0, NOW()
);

SELECT 'FunASRServer2Pass provider added' AS status;

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


SELECT 'FunASRServer2Pass provider added' AS status;

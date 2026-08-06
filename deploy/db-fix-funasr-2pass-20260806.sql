-- =============================================================
-- FunASR 2pass 配置类型修复
-- 现象：FunASR 崩溃，报 type must be array, but is string
-- 原因：智控台或旧数据把 chunk_size 存成 "5,10,5"，
--       hotwords 被存成空字符串
-- 执行：docker exec -i xiaozhi-esp32-server-db mysql -uroot -p123456 \
--       xiaozhi_esp32_server < deploy/db-fix-funasr-2pass-20260806.sql
-- 执行后：清 Redis 并重启 xiaozhi-esp32-server
-- =============================================================

UPDATE ai_model_config
SET config_json = JSON_SET(config_json, '$.chunk_size', JSON_ARRAY(5, 10, 5))
WHERE model_code = 'FunASRServer2Pass';

UPDATE ai_model_config
SET config_json = JSON_REMOVE(config_json, '$.hotwords')
WHERE model_code = 'FunASRServer2Pass';

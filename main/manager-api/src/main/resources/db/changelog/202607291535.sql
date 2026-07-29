INSERT IGNORE INTO `ai_model_provider`
VALUES (
  'SYSTEM_Intent_lightweight_router',
  'Intent',
  'lightweight_router',
  '轻量工具路由',
  '[{"key":"functions","label":"函数列表","type":"dict","dict_name":"functions"}]',
  3,
  1,
  NOW(),
  1,
  NOW()
);

INSERT IGNORE INTO `ai_model_config`
VALUES (
  'Intent_lightweight_router',
  'Intent',
  'lightweight_router',
  '轻量工具路由',
  0,
  1,
  '{\"type\": \"lightweight_router\", \"functions\": [\"web_search\", \"get_weather\", \"get_news_from_newsnow\", \"play_music\"]}',
  NULL,
  NULL,
  3,
  NULL,
  NULL,
  NULL,
  NULL
);

UPDATE `ai_model_provider`
SET `sort` = 4
WHERE `id` = 'SYSTEM_Intent_function_call' AND `sort` = 3;

UPDATE `ai_model_config`
SET `sort` = 4
WHERE `id` = 'Intent_function_call' AND `sort` = 3;

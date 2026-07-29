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
  '{\"type\": \"lightweight_router\", \"functions\": \"web_search;get_weather;get_news_from_newsnow;play_music;search_from_ragflow\"}',
  NULL,
  '轻量工具路由说明：
1. 该模式不会先调用额外 LLM 做意图识别，普通聊天默认不挂载工具，保持低延迟。
2. 函数列表表示本智能体允许轻量路由使用的工具白名单；不在列表里的服务端插件不会被该模式调用。
3. 新增工具时，通常需要先在工具/插件配置中启用并配置参数，再把函数名加入这里。
4. 仅加入函数列表还不一定会触发调用；后端还需要在 main/xiaozhi-server/core/utils/tool_router.py 中有明确路由规则。
5. RAG、天气、新闻、音乐、设备控制等按需触发；普通问答应保持 tools=false。',
  3,
  NULL,
  NULL,
  NULL,
  NULL
);

UPDATE `ai_model_config`
SET `remark` = '轻量工具路由说明：
1. 该模式不会先调用额外 LLM 做意图识别，普通聊天默认不挂载工具，保持低延迟。
2. 函数列表表示本智能体允许轻量路由使用的工具白名单；不在列表里的服务端插件不会被该模式调用。
3. 新增工具时，通常需要先在工具/插件配置中启用并配置参数，再把函数名加入这里。
4. 仅加入函数列表还不一定会触发调用；后端还需要在 main/xiaozhi-server/core/utils/tool_router.py 中有明确路由规则。
5. RAG、天气、新闻、音乐、设备控制等按需触发；普通问答应保持 tools=false。'
WHERE `id` = 'Intent_lightweight_router';

UPDATE `ai_model_provider`
SET `sort` = 4
WHERE `id` = 'SYSTEM_Intent_function_call' AND `sort` = 3;

UPDATE `ai_model_config`
SET `sort` = 4
WHERE `id` = 'Intent_function_call' AND `sort` = 3;

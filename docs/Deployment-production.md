# 生产部署指南

> 基于 `zksc` 分支（commit `363faf43`） | 更新 2026-07-30

---

## 一、前置条件

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Docker | 24+ | 含 docker compose 插件 |
| MySQL | 8.0+ | 由 docker-compose 自动部署 |
| Redis | 7+ | 由 docker-compose 自动部署 |
| 架构 | x86_64 | arm64 需本地编译镜像 |

---

## 二、部署步骤

### 2.1 拉取代码

```bash
git clone https://github.com/legend817/xiaozhi-esp32-server.git -b zksc
cd xiaozhi-esp32-server
```

### 2.2 导入数据库

如果不使用现有的数据库，先启动数据库容器：

```bash
docker compose -f deploy/docker-compose_all.yml up -d xiaozhi-esp32-server-db
sleep 15  # 等待 MySQL 初始化完成
```

导入数据（如果有备份）：

```bash
mysql -h127.0.0.1 -uroot -p123456 xiaozhi_esp32_server < xiaozhi_db_backup.sql
```

如果从零开始，数据库会自动建表，之后在智控台配置智能体和模型。

### 2.3 准备模型文件

语音识别模型需要手动下载：

```bash
# 创建模型目录
mkdir -p deploy/models/SenseVoiceSmall

# 下载模型文件（约 1.5G）
# 方式一：从 modelscope 下载
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall', local_dir='deploy/models/SenseVoiceSmall')"

# 方式二：从 huggingface 下载
# git lfs clone https://huggingface.co/ggerganov/whisper.cpp
```

### 2.4 准备配置文件

```bash
# 创建 data 目录和配置文件
touch deploy/data/.config.yaml
```

编辑 `deploy/data/.config.yaml`，填入你的配置：

```yaml
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  # 公网部署时改为公网 IP 或域名
  websocket: ws://你的公网IP:8000/xiaozhi/v1/
  vision_explain: http://你的公网IP:8003/mcp/vision/explain
manager-api:
  url: http://xiaozhi-esp32-server-web:8002/xiaozhi
  # 从智控台「参数管理」获取 server.secret
  secret: 你的server.secret
```

### 2.5 构建并启动全模块

```bash
# 全量构建
docker compose -f deploy/docker-compose_all.yml build

# 启动所有服务
docker compose -f deploy/docker-compose_all.yml up -d

# 查看启动日志
docker logs -f xiaozhi-esp32-server
```

### 2.6 验证部署

```bash
# 检查各服务状态
docker compose -f deploy/docker-compose_all.yml ps

# 确认预热缓存自动加载（启动后约 5-10 秒）
docker logs xiaozhi-esp32-server 2>&1 | grep -i warmup

# WebSocket 端口确认
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/  # 管理台
```

---

## 三、服务拓扑

```
外部流量                     Docker 内网
┌──────┐                ┌──────────────────────────────────────┐
│ ESP32 │──WebSocket──→│  xiaozhi-esp32-server :8000          │
│ 设备  │               │  xiaozhi-esp32-server-web :8002     │
└──────┘               │  xiaozhi-esp32-server-db  :3306     │
                        │  xiaozhi-esp32-server-redis :6379   │
                        └──────────────────────────────────────┘
                                  │
                           ┌──────┴──────┐
                           │  远端服务    │
                           │ RAGFlow :18008│
                           │ LLM     :23333│
                           │ 火山 TTS    │
                           └─────────────┘
```

---

## 四、公网部署额外配置

### 4.1 安全组/防火墙

| 端口 | 协议 | 用途 | 是否对外开放 |
|------|------|------|-------------|
| 8000 | TCP | WebSocket 语音交互 | **是**（ESP32 连接） |
| 8002 | TCP | 管理台 / OTA | **是**（需登录） |
| 8003 | TCP | 视觉分析接口 | 按需 |
| 3306 | TCP | MySQL | **否** |
| 6379 | TCP | Redis | **否** |

### 4.2 SSL 配置

ESP32 设备在 4G 模式下需要 wss 安全连接。推荐使用 Nginx 反向代理：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # WebSocket 代理
    location /xiaozhi/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 管理台代理
    location / {
        proxy_pass http://127.0.0.1:8002;
    }
}
```

### 4.3 MQTT 网关（可选）

如果 ESP32 通过 MQTT+UDP 协议连接，需要额外部署 MQTT 网关：

```bash
git clone https://github.com/xinnan-tech/xiaozhi-mqtt-gateway.git
cd xiaozhi-mqtt-gateway
# 参考 docs/mqtt-gateway-integration.md 配置
```

---

## 五、数据库迁移

后续如果新增数据库配置变更，会提供迁移脚本：

```bash
# 执行迁移
mysql -uroot -p xiaozhi_esp32_server < deploy/db-migrate-YYYYMMDD.sql

# 重启 server 生效
docker compose -f deploy/docker-compose_all.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

当前迁移脚本：

| 文件 | 日期 | 内容 |
|------|------|------|
| `deploy/db-migrate-20260730.sql` | 2026-07-30 | VAD 450ms、禁用思考模式、预播话术 |

---

## 六、版本升级

```bash
# 拉取最新代码
git pull

# 执行新增的数据库迁移（如果有）
mysql -uroot -p xiaozhi_esp32_server < deploy/db-migrate-新文件.sql

# 重新构建并启动
docker compose -f deploy/docker-compose_all.yml build xiaozhi-esp32-server
docker compose -f deploy/docker-compose_all.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

---

## 七、日常运维

### 查看日志

```bash
# 实时日志
docker logs -f xiaozhi-esp32-server

# 性能日志
docker logs xiaozhi-esp32-server --since 30m 2>&1 | grep LATENCY

# 预热缓存状态
docker exec xiaozhi-esp32-server python3 -c "
from core.utils.cache.redis_client import redis_client
keys = redis_client.keys('cache:warmup:*')
print(f'预热缓存: {len(keys)} 条')
"
```

### 手动触发预热

重启 server 会自动预热。如需手动触发：

```bash
docker exec xiaozhi-esp32-server python3 -c "
import asyncio
from core.utils.cache.warmup import warmup_from_ragflow
config = {'plugins': {'search_from_ragflow': {
    'base_url': 'http://82.156.31.182:18008',
    'api_key': '你的api_key',
    'dataset_ids': ['你的dataset_id'],
}}}
asyncio.run(warmup_from_ragflow(config))
print('预热完成')
"
```

### 清除 Redis 缓存

```bash
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB
```

---

## 八、troubleshooting

| 问题 | 排查 |
|------|------|
| server 启动报 `No module named 'redis'` | 检查是否成功构建，`docker logs` 确认 pip install 成功 |
| ESP32 无法连接 WebSocket | 检查安全组 8000 端口、SSL 配置、`.config.yaml` 中的 `websocket` 地址 |
| 预热日志未出现 | 检查 `search_from_ragflow` 插件的 `base_url` 和 `api_key` 配置 |
| VAD 截断说话 | 调大 `min_silence_duration_ms`（当前 450，可调回 550） |
| TTS 播报过长 | 在智控台调整智能体的回复预算策略 |

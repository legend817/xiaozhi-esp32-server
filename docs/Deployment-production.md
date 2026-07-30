# 生产部署指南

> 基于 `zksc` 分支 | 更新 2026-07-30

---

## ⚠️ 重要：缓存机制说明

系统存在多层缓存，**修改数据库配置后不会自动生效**。必须执行下面的"修改配置后"流程。

| 缓存层 | 存储位置 | 存活周期 | 清除方式 |
|--------|----------|----------|----------|
| Java API 缓存 | Redis `server:config` 等 key | 永久（直到手动清） | `FLUSHDB` |
| Python 配置缓存 | 内存 | 服务重启消失 | 重启容器 |
| 预热缓存 | Redis `cache:warmup:*` | 7 天 TTL | `FLUSHDB` 或等待到期 |
| RAGFlow 查询缓存 | Redis `cache:ragflow:*` | 7 天 TTL | `FLUSHDB` 或等待到期 |

---

## 一、前置条件

Docker 24+，x86_64 架构。

---

## 二、首次部署

### 2.1 拉取代码

```bash
git clone https://github.com/legend817/xiaozhi-esp32-server.git -b zksc
cd xiaozhi-esp32-server
```

### 2.2 启动数据库

```bash
docker compose -f deploy/docker-compose_all.yml up -d xiaozhi-esp32-server-db
sleep 15
```

### 2.3 导入数据

首次部署运行迁移脚本：

```bash
docker exec -i xiaozhi-esp32-server-db mysql -uroot -p123456 \
  xiaozhi_esp32_server < deploy/db-migrate-20260730.sql
```

如有完整备份则导入：

```bash
docker exec -i xiaozhi-esp32-server-db mysql -uroot -p123456 \
  xiaozhi_esp32_server < xiaozhi_db_backup.sql
```

### 2.4 准备模型文件

```bash
mkdir -p deploy/models/SenseVoiceSmall
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall', local_dir='deploy/models/SenseVoiceSmall')"
```

### 2.5 配置 .config.yaml

```bash
touch deploy/data/.config.yaml
```

写入以下内容（替换 IP 和 secret）：

```yaml
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  websocket: ws://你的公网IP:8000/xiaozhi/v1/
  vision_explain: http://你的公网IP:8003/mcp/vision/explain
manager-api:
  url: http://xiaozhi-esp32-server-web:8002/xiaozhi
  secret: 你的server.secret
```

### 2.6 构建镜像

```bash
docker build -f Dockerfile-server -t xiaozhi-esp32-server:production .
```

### 2.7 启动全部服务

```bash
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.prod.yml up -d
```

### 2.8 验证

```bash
docker compose -f deploy/docker-compose_all.yml ps
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/
```

---

## 三、日常运维

### 修改数据库配置后

**你在智控台（或直接改 MySQL）修改了任何配置后，必须执行以下步骤，否则不生效：**

```bash
# 1. 清 Redis 缓存（必须！Java API 和 Python 都从 Redis 读缓存）
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB

# 2. 重启 server（清 Python 内存缓存）
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

**常见需要此操作的场景：**
- 改了 ASR/TTS/LLM 的模型配置（地址、密钥、参数）
- 改了 VAD 参数（静音阈值、尾延迟）
- 改了智能体绑定的模型
- 改了预热缓存相关的 RAGFlow 配置
- 改了智能体的 system prompt

### 同步代码更新

```bash
git pull
docker build -f Dockerfile-server -t xiaozhi-esp32-server:production .
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

如果新版本带了数据库迁移脚本：

```bash
docker exec -i xiaozhi-esp32-server-db mysql -uroot -p123456 \
  xiaozhi_esp32_server < deploy/db-migrate-YYYYMMDD.sql
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

### 查看日志

```bash
docker logs -f xiaozhi-esp32-server
docker logs xiaozhi-esp32-server --since 30m 2>&1 | grep LATENCY
```

### 查看预热缓存

```bash
docker exec xiaozhi-esp32-server python3 -c "
from core.utils.cache.redis_client import redis_client
keys = redis_client.keys('cache:warmup:*')
print(f'预热缓存: {len(keys)} 条')
"
```

---

## 四、故障排查

| 现象 | 排查 |
|------|------|
| 改配置不生效 | 第三步没做：必须先 `FLUSHDB` 再重启 server |
| ESP32 连不上 | 检查安全组 8000 端口，`.config.yaml` 中 `websocket` 地址 |
| 远程 FunASR 崩溃 | 检查 MySQL 中 `chunk_size` 是数组 `[5,10,5]` 不是字符串 `"5,10,5"`；执行迁移脚本 |
| 预热未加载 | 检查智控台中 `search_from_ragflow` 配置 |
| VAD 截断说话 | 调大 `min_silence_duration_ms`（智控台→模型管理→VAD_SileroVAD） |

---

## 五、端口说明

| 端口 | 用途 | 对外开放 |
|------|------|----------|
| 8000 | WebSocket 语音 | **是** |
| 8002 | 管理台/OTA | **是** |
| 8003 | 视觉接口 | 按需 |
| 3306 | MySQL | **否** |
| 6379 | Redis | **否** |

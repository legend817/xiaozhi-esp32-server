# 生产部署指南

> 基于 `zksc` 分支 | 更新 2026-07-30

---

## 一、前置条件

Docker 24+，x86_64 架构。

---

## 二、部署步骤

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

### 2.3 导入数据（可选）

有备份文件则导入，首次部署可跳过：

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
docker logs --since 10s xiaozhi-esp32-server 2>&1 | grep -i warmup
```

---

## 三、版本升级

```bash
git pull
docker build -f Dockerfile-server -t xiaozhi-esp32-server:production .
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

---

## 四、日常运维

```bash
# 日志
docker logs -f xiaozhi-esp32-server
docker logs xiaozhi-esp32-server --since 30m 2>&1 | grep LATENCY

# 预热状态
docker exec xiaozhi-esp32-server python3 -c "
from core.utils.cache.redis_client import redis_client
keys = redis_client.keys('cache:warmup:*')
print(f'预热缓存: {len(keys)} 条')
"

# 清除 Redis 缓存
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB
```

---

## 五、端口说明

| 端口 | 用途 | 对外开放 |
|------|------|----------|
| 8000 | WebSocket 语音 | **是** |
| 8002 | 管理台/OTA | **是** |
| 8003 | 视觉接口 | 按需 |
| 3306 | MySQL | **否** |
| 6379 | Redis | **否** |

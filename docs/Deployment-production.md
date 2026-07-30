# 生产部署指南

> 基于 `zksc` 分支（commit `013d80d4`）| 更新 2026-07-30

---

## 一、前置条件

| 依赖 | 说明 |
|------|------|
| Docker 24+ | 含 docker compose 插件 |
| 架构 | x86_64 |

服务依赖（MySQL、Redis）由 docker-compose 自动管理，无需手动安装。

---

## 二、部署步骤

### 2.1 拉取代码

```bash
git clone https://github.com/legend817/xiaozhi-esp32-server.git -b zksc
cd xiaozhi-esp32-server
```

### 2.2 导入数据库

```bash
# 先启动数据库
docker compose -f deploy/docker-compose_all.yml up -d xiaozhi-esp32-server-db

# 等待 MySQL 就绪（约 15 秒）
sleep 15

# 导入数据（如果有备份文件）
mysql -h127.0.0.1 -uroot -p123456 xiaozhi_esp32_server < xiaozhi_db_backup.sql
```

> 首次部署没有备份文件可跳过导入。系统启动后会自动建表，之后在智控台配置智能体即可。

### 2.3 准备模型文件

```bash
# 创建目录
mkdir -p deploy/models/SenseVoiceSmall

# 下载语音识别模型
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall', local_dir='deploy/models/SenseVoiceSmall')"
```

### 2.4 配置 .config.yaml

```bash
touch deploy/data/.config.yaml
```

编辑 `deploy/data/.config.yaml`：

```yaml
server:
  ip: 0.0.0.0
  port: 8000
  http_port: 8003
  # 将 IP 替换为你的公网 IP 或域名
  websocket: ws://你的公网IP:8000/xiaozhi/v1/
  vision_explain: http://你的公网IP:8003/mcp/vision/explain
manager-api:
  url: http://xiaozhi-esp32-server-web:8002/xiaozhi
  # 从智控台「参数管理」获取 server.secret 填入
  secret: 你的server.secret
```

### 2.5 构建并启动

```bash
# 构建 server 镜像（使用与 compose 相同的镜像名，覆盖远端拉取）
docker build -f Dockerfile-server \
  -t ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest .

# 构建 web 镜像（首次部署需要）
docker compose -f deploy/docker-compose_all.yml build xiaozhi-esp32-server-web

# 启动全部服务
docker compose -f deploy/docker-compose_all.yml up -d

# 查看启动日志
docker logs --tail 20 xiaozhi-esp32-server
```

### 2.6 验证

```bash
# 服务状态
docker compose -f deploy/docker-compose_all.yml ps

# 管理台可访问
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/
# 预期返回 200

# 预热缓存自动加载（启动后约 5-10 秒）
docker logs --since 10s xiaozhi-esp32-server 2>&1 | grep -i warmup
```

---

## 三、服务拓扑

```
┌──────┐                ┌──────────────────────────────────────┐
│ ESP32 │──WebSocket──→│  xiaozhi-esp32-server  :8000         │
│ 设备  │               │  xiaozhi-esp32-server-web :8002     │
└──────┘               │  xiaozhi-esp32-server-db  :3306     │
                        │  xiaozhi-esp32-server-redis :6379   │
                        └──────────┬───────────────────────────┘
                                   │
                            ┌──────┴──────┐
                            │  远端服务    │
                            │ RAGFlow     │
                            │ LLM (Qwen3) │
                            │ 火山 TTS    │
                            └─────────────┘
```

---

## 四、公网部署

### 端口

| 端口 | 用途 | 对外开放 |
|------|------|----------|
| 8000 | WebSocket 语音交互 | **是** |
| 8002 | 管理台 / OTA | **是** |
| 8003 | 视觉分析接口 | 按需 |
| 3306 | MySQL | **否** |
| 6379 | Redis | **否** |

### SSL（4G 模式需 wss）

推荐 Nginx 反向代理：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location /xiaozhi/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        proxy_pass http://127.0.0.1:8002;
    }
}
```

---

## 五、版本升级

```bash
# 拉取最新代码
git pull

# 执行新增的数据库迁移（如果有）
mysql -uroot -p xiaozhi_esp32_server < deploy/db-migrate-新文件.sql

# 重新构建 server 镜像
docker build -f Dockerfile-server \
  -t ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:server_latest .

# 重启
docker compose -f deploy/docker-compose_all.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
```

---

## 六、日常运维

```bash
# 实时日志
docker logs -f xiaozhi-esp32-server

# 性能延迟日志
docker logs xiaozhi-esp32-server --since 30m 2>&1 | grep LATENCY

# 预热缓存状态
docker exec xiaozhi-esp32-server python3 -c "
from core.utils.cache.redis_client import redis_client
keys = redis_client.keys('cache:warmup:*')
print(f'预热缓存: {len(keys)} 条')
"

# 手动清除 Redis 缓存
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB
```

---

## 七、常见问题

| 问题 | 排查 |
|------|------|
| ESP32 连不上 | 检查安全组 8000 端口、`.config.yaml` 中 `websocket` 地址 |
| 预热未加载 | 检查智控台中 `search_from_ragflow` 插件的 `base_url` 和 `api_key` |
| VAD 截断说话 | 调大 `min_silence_duration_ms`（智控台→模型管理→VAD_SileroVAD） |
| TTS 播报过长 | 智控台调整智能体的回复预算策略 |
| 启动报 `No module named 'redis'` | 确认 `docker build` 成功，检查 Dockerfile 中 pip install 步骤 |

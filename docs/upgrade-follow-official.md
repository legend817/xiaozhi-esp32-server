# 跟随 xiaozhi 官方升级流程

本文适用于在本地 `zksc` 分支维护自定义改动，同时需要跟随
`xinnan-tech/xiaozhi-esp32-server` 官方 `main` 升级的情况。

## 一、仓库结构

- `upstream`：官方仓库 `xinnan-tech/xiaozhi-esp32-server`
- `origin`：个人 fork 仓库
- 本地开发分支：`zksc`

升级原则：

- 不直接用官方 `main` 覆盖 `zksc`。
- 不把官方初始化 SQL 直接覆盖现有数据库。
- 数据库升级优先使用官方 Liquibase 新增变更，不手工重跑全部旧初始化 SQL。
- 升级后保留自定义模型配置、音色、智能体、密钥等数据。

## 二、升级前准备

```bash
git switch zksc
git status
```

如有未提交改动，先提交：

```bash
git add .
git commit -m "chore: 升级前提交当前改动"
```

或者暂存：

```bash
git stash
```

## 三、拉取官方更新

```bash
git fetch upstream
git diff --stat upstream/main...zksc
```

先确认官方改动范围，再执行合并。

## 四、合并官方 main 到 zksc

```bash
git merge upstream/main
```

出现冲突时：

```bash
git status
```

手动处理冲突文件后：

```bash
git add <冲突文件>
git commit -m "merge: 合并 upstream/main 到 zksc"
```

重点核对本地修改过的文件：

- `main/xiaozhi-server/core/providers/asr/fun_server_2pass.py`
- `main/xiaozhi-server/core/utils/asr_text.py`
- `main/xiaozhi-server/core/providers/tts/triton_cosyvoice.py`
- `main/manager-web/src/components/TtsModel.vue`
- `deploy/*.sql`

## 五、数据库升级

### 1. 先备份当前数据库

```bash
docker exec xiaozhi-esp32-server-db mysqldump \
  --single-transaction --routines --triggers --events --set-gtid-purged=OFF \
  -uroot -p123456 xiaozhi_esp32_server > deploy/db-backup-before-upgrade-$(date +%Y%m%d).sql
```

### 2. 查看官方新增的数据库变更

```bash
git diff --name-only upstream/main...HEAD -- \
  main/manager-api/src/main/resources/db/changelog \
  'deploy/*.sql'
```

### 3. Liquibase 自动升级

本项目管理端使用 Liquibase：

- 当前数据库已经有 `DATABASECHANGELOG` 表。
- 合并官方代码后，重启 `xiaozhi-esp32-server-web`，Liquibase 会自动执行新增
  changelog。
- 不需要手动执行所有旧 changelog。

### 4. 手动迁移脚本

如果官方同时提供了独立迁移脚本，例如：

```text
deploy/db-migrate-YYYYMMDD.sql
```

按官方文档执行，例如：

```bash
docker exec -i xiaozhi-esp32-server-db mysql -uroot -p123456 \
  xiaozhi_esp32_server < deploy/db-migrate-YYYYMMDD.sql
```

## 六、重启服务

清 Redis：

```bash
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHDB
```

重建并重启本地开发 server：

```bash
env XIAOZHI_DEV_TAG="$(git rev-parse --short HEAD)-dev" \
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml \
  build xiaozhi-esp32-server

env XIAOZHI_DEV_TAG="$(git rev-parse --short HEAD)-dev" \
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

如果官方改了 manager-api/manager-web，还需要更新或重建
`xiaozhi-esp32-server-web`：

```bash
docker compose -f deploy/docker-compose_all.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server-web
```

检查启动日志：

```bash
docker logs --tail 100 xiaozhi-esp32-server
docker logs --tail 100 xiaozhi-esp32-server-web
```

## 七、推送升级结果

```bash
git push origin zksc
```

## 八、升级后生成新版初始化 SQL

升级并验证完成后，可以重新生成一份匹配当前版本的完整初始化 SQL：

```bash
docker exec xiaozhi-esp32-server-db mysqldump \
  --single-transaction --routines --triggers --events --set-gtid-purged=OFF \
  -uroot -p123456 xiaozhi_esp32_server > deploy/db-init-current-$(date +%Y%m%d).sql
```

注意：

- `db-init-current-*.sql` 只用于新环境初始化。
- 不用于升级已有数据库，避免覆盖自定义数据。
- 生成后应导入临时库验证，确认表数量、关键表行数和 checksum 与当前库一致。

## 九、常见注意事项

- 官方初始化 SQL 里的默认模型配置、音色、字典可能和本地不同，不要直接覆盖。
- 本地自定义配置优先保存在 manager-api 数据库中，不写死在代码里。
- 官方升级改到本地已修改文件时，必须人工确认冲突，避免丢失之前的修复。
- 升级前先备份数据库和 `deploy/data/.config.yaml`。

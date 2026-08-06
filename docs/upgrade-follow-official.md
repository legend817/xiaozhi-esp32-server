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

## 十、实操版：完整执行顺序（2026-08-06 已走通）

下面是本次实际执行并验证通过的完整流程，适合一步一步照做。

### 1. 提交当前本地工作

```bash
git switch zksc
git status
git add .
git commit -m "chore: 升级前提交当前改动"
```

如果有不想提交的本地文件，先移出仓库目录，或加入 `.gitignore`。

### 2. 拉取官方最新代码

```bash
git fetch upstream
git diff --stat upstream/main...zksc
```

先看差异规模，不要直接合并。

### 3. 创建测试分支，试合并

```bash
git switch -c merge-test zksc
git merge --no-commit upstream/main
```

这一步不会自动提交。查看合并状态：

```bash
git status
```

如果冲突太多，可以安全放弃：

```bash
git merge --abort
git switch zksc
git branch -D merge-test
```

### 4. 处理冲突

本次实测遇到两个冲突：

`db.changelog-master.yaml`：

- `zksc` 新增了 `202607291535`
- `upstream/main` 新增了 `202607290930`

处理方式：两个 changeset 都保留，官方 `202607290930` 放前面，自己的
`202607291535` 放后面。

`plugin_executor.py`：

- `zksc` 用 `plugin_configs.get(func_name, {}).get("description", "")`
- `upstream/main` 用 `self._get_plugin_description(func_name)`

处理方式：采用官方的 `_get_plugin_description()`，因为它支持模块名和函数名
双层查找，兼容性更好。

解决冲突后：

```bash
git add <冲突文件>
git commit -m "merge: 试合并 upstream/main"
```

### 5. 合并回 zksc

```bash
git switch zksc
git merge --no-ff merge-test -m "merge: 合并 upstream/main 到 zksc"
git branch -D merge-test
```

### 6. 备份数据库

```bash
docker exec xiaozhi-esp32-server-db mysqldump \
  --single-transaction --routines --triggers --events --set-gtid-purged=OFF \
  -uroot -p123456 xiaozhi_esp32_server > deploy/db-backup-before-upgrade-$(date +%Y%m%d).sql
```

### 7. 查看官方新增数据库变更

```bash
git diff --name-only upstream/main...HEAD -- \
  main/manager-api/src/main/resources/db/changelog \
  'deploy/*.sql'
```

### 8. 构建本地 web 镜像并让 Liquibase 自动迁移

如果当前 `web_latest` 镜像比较旧，jar 里没有官方新增 changelog，就必须用
合并后的源码重新构建 web。

先确认 `.dockerignore` 不要排除 `main/manager-api` 和 `main/manager-web`：

```text
# Modules that are not copied by Dockerfile-server.
main/manager-mobile/
main/digital-human/
```

构建 web 镜像：

```bash
WEB_TAG="$(git rev-parse --short HEAD)-dev"
docker build -f Dockerfile-web -t "xiaozhi-esp32-server-web:${WEB_TAG}" .
```

由于 compose 的 web 服务固定使用 `web_latest` 镜像，本地测试环境可以把本地
镜像临时标记成 `web_latest`：

```bash
docker tag "xiaozhi-esp32-server-web:${WEB_TAG}" \
  ghcr.nju.edu.cn/xinnan-tech/xiaozhi-esp32-server:web_latest
```

重启 web：

```bash
docker compose -f deploy/docker-compose_all.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server-web
```

查看 web 日志，确认 Liquibase 执行：

```bash
docker logs --tail 100 xiaozhi-esp32-server-web
```

正常情况会看到：

```text
Running Changeset: db/changelog/db.changelog-master.yaml::202607290930::cgd
SQL in file classpath:db/changelog/202607290930.sql executed
```

确认 `DATABASECHANGELOG` 已记录官方路径：

```sql
SELECT ID, AUTHOR, FILENAME, DATEEXECUTED, ORDEREXECUTED, MD5SUM
FROM DATABASECHANGELOG
WHERE ID = '202607290930';
```

`FILENAME` 必须是：

```text
db/changelog/db.changelog-master.yaml
```

不要使用临时 changelog 路径手动执行，否则 `FILENAME` 会变成
`file:/tmp/...`，后续官方 Liquibase 会误判未执行并重复运行。

### 9. 构建并重启 server

```bash
DEV_TAG="$(git rev-parse --short HEAD)-dev"

env XIAOZHI_DEV_TAG="${DEV_TAG}" \
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml \
  build xiaozhi-esp32-server

env XIAOZHI_DEV_TAG="${DEV_TAG}" \
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml \
  up -d --no-deps --force-recreate xiaozhi-esp32-server
```

查看 server 日志：

```bash
docker logs --tail 100 xiaozhi-esp32-server
```

日志里应显示：

```text
源码版本		ffcdae83-dev
```

### 10. 清 Redis

```bash
docker exec xiaozhi-esp32-server-redis redis-cli FLUSHALL
```

### 11. 验证服务

```bash
docker ps
docker logs --tail 80 xiaozhi-esp32-server-web
docker logs --tail 80 xiaozhi-esp32-server
```

web 容器内检查智控台：

```bash
docker exec xiaozhi-esp32-server-web sh -c \
  'wget -qO- --timeout=3 http://127.0.0.1:8002/ | head -5'
```

### 12. 提交剩余改动并推送

```bash
git status
git add .dockerignore
git commit -m "build: 允许 web 镜像构建使用 manager-api/manager-web 源码"
git push origin zksc
```

数据库备份文件按项目约定保留本地，不要提交到仓库。

### 13. 升级后重新生成初始化 SQL

```bash
docker exec xiaozhi-esp32-server-db mysqldump \
  --single-transaction --routines --triggers --events --set-gtid-purged=OFF \
  -uroot -p123456 xiaozhi_esp32_server > deploy/db-init-current-$(date +%Y%m%d).sql
```

生成后导入临时库验证表数量和关键数据 checksum。

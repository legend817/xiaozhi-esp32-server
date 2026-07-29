# 当前开发交接说明

日期：2026-07-30

本文只记录当前应该遵守的开发方式和优化方向。历史测试细节保留在其它 `docs/*.md` 中。

## 开发边界

- 当前只改 `main/xiaozhi-server` 后端。
- 不改管理端前端，不通过前端隐藏或绕过原有能力。
- `Intent_nointent` 必须保持原始语义：无意图、无工具。
- 需要低延迟工具能力时，使用 `Intent_lightweight_router`。

## 本地开发容器

开发镜像使用同一个后端容器名，不会同时启动生产和开发两个后端。

```bash
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml build xiaozhi-esp32-server
docker compose -f deploy/docker-compose_all.yml -f deploy/docker-compose.dev.yml up -d --no-deps --force-recreate xiaozhi-esp32-server
docker logs --tail 100 xiaozhi-esp32-server
```

端口：

- WebSocket：`8000`
- 管理端 / OTA：`8002`
- 视觉接口：`8003`

不要提交 `deploy/` 下的运行态数据、数据库、上传文件和模型文件。

## 当前 RAG 策略

当前不采用 RAG 首句抽取。

已删除的思路：

```text
RAG 返回 chunk
  ↓
从 chunk 中抽一句先播
  ↓
LLM 继续组织正式答案
```

保留的策略：

- 字段型问题走直答快路径，例如地址、电话、人数。
- 复杂问题走 RAG + LLM 流式生成。
- LLM 输出由 `StreamingTextSegmenter` 按自然标点和长度分段送 TTS。
- 地址类直答会裁掉第二句补充说明，只保留地址句。
- 查不到知识库事实时直接说明未查到，不让 LLM 编。

高频企业事实应优先放入快答 Q/A 库，而不是依赖长资料片段。

## RAGFlow 导入文件

当前推荐导入文件：

```text
docs/ragflow/enterprise_facts_qa_import.csv
```

它是两列、无表头：

```text
问题,答案
```

审计文件：

```text
docs/ragflow/enterprise_facts_qa_audit.csv
```

重新生成：

```bash
python3 tools/build_enterprise_facts_qa.py
```

导入原则：

- 先只用快答库测地址、电话、主营业务、人数等基础事实。
- 长资料库保留给“详细介绍、发展历程、专家详情、临床中心详情”等综合问题。
- 暂时不要先做复杂多库路由；先把一个快答库测稳。

## 测试

后端关键测试：

```bash
cd main/xiaozhi-server
python3 -m unittest discover -s tests
```

RAG 相关最小测试：

```bash
cd main/xiaozhi-server
python3 -m unittest discover -s tests -p 'test_rag_context.py'
```

测试关注点：

- 普通聊天不带工具。
- `Intent_lightweight_router` 只在明确命中时调用对应工具。
- 企业字段问答能直答。
- RAG 混合片段不能诱导 LLM 编造地址、电话等事实。
- TTS 输出不出现工具调用 JSON 或函数名。

## 提交前检查

```bash
git status --short
git diff --stat
cd main/xiaozhi-server && python3 -m unittest discover -s tests
```

提交前确认：

- 没有提交模型文件、数据库、上传文件、临时日志。
- 新增 RAG 数据文件有审计文件或生成脚本。
- 文档说明与当前默认策略一致。

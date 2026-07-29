# Enterprise Facts Q/A Import Notes

生成目标：把 `identity.csv` 规整为企业客服快答事实卡片，减少重复问法挤占 RAG top_k。

## Files

- `enterprise_facts_qa_import.csv`: RAGFlow 导入文件，两列，无表头，列顺序为问题、答案。
- `enterprise_facts_qa_audit.csv`: 审计文件，包含分类、优先级、来源行号和答案哈希。

## Import Rules

- 字段型问题（地址、电话、人数、地点）答案第一句必须直接给结论。
- 同一事实只保留少量高质量问法，避免 20 条以上重复别名把其他事实挤出检索结果。
- 企业总部地址、电话、科学家数量、临床应用中心位置做了事实合并，避免同义答案互相竞争。
- 长资料仍建议保留在资料库，用于详细介绍类问题；本文件主要用于快问快答。

## Summary

- facts: 48
- import rows: 227

## Category Counts

- address: 1
- assistant_identity: 1
- business: 6
- certification: 1
- facility_location: 1
- model_identity: 1
- personnel: 11
- personnel_count: 1
- phone: 1
- timeline: 24

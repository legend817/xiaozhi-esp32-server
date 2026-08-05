"""Startup warmup: pre-populate Redis cache from RAGFlow dataset chunks.

On server startup this module iterates each configured RAGFlow dataset,
fetches all chunks via the paginated documents/chunks API, and writes
every unique question-answer pair into Redis with a 7-day TTL.

This ensures even the first-ever query for a known fact (address, phone, …)
hits Redis instantly instead of waiting for a remote RAGFlow retrieval.
"""

import asyncio
import logging
import re
import time

from core.utils.cache.redis_client import redis_client
from core.utils.rag_context import build_enterprise_faq_cache_alias

WARMUP_NAMESPACE = "warmup"
WARMUP_TTL = 604800       # 7 days
WARMUP_BATCH = 100        # chunks per page
_CHUNK_QA_RE = re.compile(
    r"(?:问题|提问)\s*[:：]\s*(.*?)\s+(?:回答|答案)\s*[:：]\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

logger = logging.getLogger("cache_warmup")


async def warmup_from_ragflow(config: dict):
    """Warm up Redis cache from all configured RAGFlow datasets."""
    ragflow_config = config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = _normalize_ids(ragflow_config.get("dataset_ids", []))
    # 跳过配置中的占位符（如 123456789）
    placeholders = {"123456789", "你的dataset_id", "ragflow-xxx"}
    dataset_ids = [d for d in dataset_ids if d not in placeholders]

    if not base_url or not api_key or not dataset_ids:
        logger.info("warmup skipped: no RAGFlow datasets configured")
        return

    if not redis_client.available:
        logger.warning("warmup skipped: Redis unavailable")
        return

    total_pairs = 0
    for dataset_id in dataset_ids:
        pairs = await _warmup_dataset(base_url, api_key, dataset_id)
        total_pairs += pairs

    logger.info("warmup complete: %d Q&A pairs cached", total_pairs)


async def _warmup_dataset(base_url: str, api_key: str, dataset_id: str) -> int:
    """Fetch all documents for *dataset_id*, then all their chunks, cache each QA pair."""
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"}
    pairs = 0

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0), verify=False
    ) as client:
        # 1. List documents
        doc_url = f"{base_url}/api/v1/datasets/{dataset_id}/documents"
        try:
            resp = await client.get(doc_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("warmup: failed to list documents for %s: %s", dataset_id, exc)
            return 0

        docs = (data.get("data") or {}).get("docs", []) if data.get("code") == 0 else []
        if not docs:
            logger.info("warmup: no documents in dataset %s", dataset_id)
            return 0

        for doc in docs:
            doc_id = doc.get("id")
            if not doc_id:
                continue
            chunk_count = doc.get("chunk_count", 0)
            if not chunk_count:
                continue

            # 2. Fetch chunks page by page
            offset = 0
            while offset < chunk_count:
                chunk_url = (
                    f"{base_url}/api/v1/datasets/{dataset_id}/documents/{doc_id}/chunks"
                    f"?offset={offset}&limit={WARMUP_BATCH}"
                )
                try:
                    cresp = await client.get(chunk_url, headers=headers)
                    cresp.raise_for_status()
                    cdata = cresp.json()
                except Exception as exc:
                    logger.warning("warmup: chunk fetch error at offset %d: %s", offset, exc)
                    break

                chunks = (cdata.get("data") or {}).get("chunks", [])
                if not chunks:
                    break

                for chunk in chunks:
                    content = chunk.get("content", "")
                    if not content:
                        continue
                    q, a = _parse_qa(content)
                    if q and a:
                        _cache_qa(q, a)
                        pairs += 1

                offset += len(chunks)

    return pairs


def _parse_qa(content: str) -> tuple:
    """Extract (question, answer) from a RAGFlow chunk content string.

    Handles formats:
      问题：xxx\t回答：xxx
      问题：xxx 回答：xxx
      提问：xxx\t答案：xxx
    """
    text = str(content or "").strip()
    # Try structured Q/A first (from QA-imported xlsx)
    m = _CHUNK_QA_RE.search(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Fallback: tab-separated 问题：...	回答：...
    for sep in ("\t", "\n", "  "):
        parts = text.split(sep)
        if len(parts) >= 2:
            q_part = _strip_prefix(parts[0], ("问题", "提问"))
            a_part = _strip_prefix(parts[-1], ("回答", "答案"))
            if q_part and a_part:
                return q_part.strip(), a_part.strip()
    return "", ""


def _strip_prefix(text: str, prefixes: tuple) -> str:
    for p in prefixes:
        for sep in ("：", ":", " "):
            marker = f"{p}{sep}"
            if text.startswith(marker):
                return text[len(marker):]
    return text


def _cache_qa(question: str, answer: str):
    """Write a Q&A pair into Redis under exact + alias keys."""
    # 1. Exact normalized match
    key = _normalize(question)
    if key:
        redis_client.set(f"cache:{WARMUP_NAMESPACE}:{key}", answer, ttl=WARMUP_TTL)

    # 2. Alias-based match (e.g., phone:公司, phone:中科生创集团)
    cat, alias = build_enterprise_faq_cache_alias(question)
    if alias:
        alias_key = f"cache:{WARMUP_NAMESPACE}:alias:{alias}"
        # Only overwrite if not already stored (first one wins)
        if not redis_client.get(alias_key):
            redis_client.set(alias_key, answer, ttl=WARMUP_TTL)
        # Also store a category-only fallback for subject-agnostic queries
        generic_key = f"cache:{WARMUP_NAMESPACE}:cat:{cat}"
        if not redis_client.get(generic_key):
            redis_client.set(generic_key, answer, ttl=WARMUP_TTL)


def _normalize_ids(ids) -> list:
    """Normalize dataset_ids to a list of strings."""
    if isinstance(ids, str):
        return [item.strip() for item in ids.split(",") if item.strip()]
    if not isinstance(ids, list):
        return [str(ids)] if ids else []
    return [str(item).strip() for item in ids if str(item).strip()]

def _normalize(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    text = text.strip("，,。.!！?？;；:：、…～~\"'“”‘’`()（）[]【】")
    return text


def match_warmup(question: str) -> str:
    """Check the warmup cache for a direct answer.

    Matching order:
      1. Exact normalized match
      2. Alias match (via ``build_enterprise_faq_cache_alias``)
      3. Category-only fallback
    """
    q = str(question or "").strip()
    if not q:
        return None

    # 1. Exact normalized match
    key = _normalize(q)
    if key:
        result = redis_client.get(f"cache:{WARMUP_NAMESPACE}:{key}")
        if result is not None:
            return result

    # 2. Alias match
    cat, alias = build_enterprise_faq_cache_alias(q)
    if alias:
        result = redis_client.get(f"cache:{WARMUP_NAMESPACE}:alias:{alias}")
        if result is not None:
            return result

    # 3. Category-only fallback (subject-agnostic, e.g., "公司" vs "中科生创集团")
    if cat:
        result = redis_client.get(f"cache:{WARMUP_NAMESPACE}:cat:{cat}")
        if result is not None:
            return result

    return None

import json
import time
import hashlib
import re
import httpx
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING
from core.utils.cache.manager import cache_manager, CacheType
from core.utils.rag_context import (
    build_enterprise_faq_cache_alias,
    build_enterprise_faq_retrieval_question,
    extract_entity_query_term,
    filter_contexts_containing_term,
    select_direct_qa_answer,
    select_enterprise_location_answer,
    select_rag_contexts,
)
from core.utils.ragflow_http import ragflow_http_client_pool

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

DEFAULT_PAGE_SIZE = 3
DEFAULT_TOP_K = 16
DEFAULT_SIMILARITY_THRESHOLD = 0.3
DEFAULT_ENTITY_FALLBACK_THRESHOLD = 0.18
DEFAULT_MAX_CONTEXT_CHUNKS = 3
DEFAULT_MAX_CONTEXT_CHARS = 2200
DEFAULT_CACHE_TTL = 600
# The fast path is still guarded by exact-question/consensus checks and falls
# back to the LLM whenever retrieval is ambiguous or requires synthesis.
DEFAULT_DIRECT_ANSWER_ENABLED = True
DEFAULT_DIRECT_ANSWER_MIN_SIMILARITY = 0.36
DEFAULT_DIRECT_ANSWER_MIN_SUPPORT = 2
DEFAULT_DIRECT_ANSWER_SCORE_GAP = 0.03
DEFAULT_DIRECT_ANSWER_MAX_CHARS = 75
DEFAULT_DIRECT_ALIAS_CACHE_ENABLED = True
DEFAULT_STAGED_FIRST_REPLY_ENABLED = True
DEFAULT_STAGED_FIRST_REPLY = ""
DIRECT_ANSWER_ALIAS_CACHE_NAMESPACE = "direct_answer_alias"
# Bump whenever direct-answer parsing or safety rules change, so an in-process
# cache can never preserve an answer produced by an older rule set.
RAG_CACHE_SCHEMA_VERSION = "direct-qa-v4"

# 定义基础的函数描述模板
SEARCH_FROM_RAGFLOW_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "search_from_ragflow",
        "description": "从知识库中查询信息",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "查询的问题"}},
            "required": ["question"],
        },
    },
}


@register_function(
    "search_from_ragflow", SEARCH_FROM_RAGFLOW_FUNCTION_DESC, ToolType.SYSTEM_CTL
)
async def search_from_ragflow(conn: "ConnectionHandler", question=None):
    # 确保字符串参数正确处理编码
    if question and isinstance(question, str):
        # 确保问题参数是UTF-8编码的字符串
        pass
    else:
        question = str(question) if question is not None else ""

    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = ragflow_config.get("dataset_ids", [])
    page_size = _get_int_config(ragflow_config, "page_size", DEFAULT_PAGE_SIZE, 1, 30)
    top_k = _get_int_config(ragflow_config, "top_k", DEFAULT_TOP_K, 1, 1024)
    similarity_threshold = _get_float_config(
        ragflow_config, "similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD, 0.0, 1.0
    )
    entity_fallback_threshold = _get_float_config(
        ragflow_config,
        "entity_fallback_threshold",
        DEFAULT_ENTITY_FALLBACK_THRESHOLD,
        0.0,
        similarity_threshold,
    )
    max_context_chunks = _get_int_config(
        ragflow_config, "max_context_chunks", DEFAULT_MAX_CONTEXT_CHUNKS, 1, page_size
    )
    max_context_chars = _get_int_config(
        ragflow_config, "max_context_chars", DEFAULT_MAX_CONTEXT_CHARS, 300, 10000
    )
    cache_ttl = _get_int_config(ragflow_config, "cache_ttl", DEFAULT_CACHE_TTL, 0, 86400)
    cache_enabled = _get_bool_config(ragflow_config, "cache_enabled", True)
    direct_answer_enabled = _get_bool_config(
        ragflow_config, "direct_answer_enabled", DEFAULT_DIRECT_ANSWER_ENABLED
    )
    direct_alias_cache_enabled = _get_bool_config(
        ragflow_config,
        "direct_alias_cache_enabled",
        DEFAULT_DIRECT_ALIAS_CACHE_ENABLED,
    )
    staged_first_reply_enabled = _get_bool_config(
        ragflow_config,
        "staged_first_reply_enabled",
        DEFAULT_STAGED_FIRST_REPLY_ENABLED,
    )
    staged_first_reply = str(
        ragflow_config.get("staged_first_reply", DEFAULT_STAGED_FIRST_REPLY) or ""
    ).strip()
    direct_answer_min_similarity = _get_float_config(
        ragflow_config,
        "direct_answer_min_similarity",
        DEFAULT_DIRECT_ANSWER_MIN_SIMILARITY,
        0.0,
        1.0,
    )
    direct_answer_min_support = _get_int_config(
        ragflow_config,
        "direct_answer_min_support",
        DEFAULT_DIRECT_ANSWER_MIN_SUPPORT,
        1,
        page_size,
    )
    direct_answer_score_gap = _get_float_config(
        ragflow_config,
        "direct_answer_score_gap",
        DEFAULT_DIRECT_ANSWER_SCORE_GAP,
        0.0,
        1.0,
    )
    direct_answer_max_chars = _get_int_config(
        ragflow_config,
        "direct_answer_max_chars",
        DEFAULT_DIRECT_ANSWER_MAX_CHARS,
        10,
        300,
    )
    entity_term = extract_entity_query_term(question)
    direct_alias_category, direct_alias = build_enterprise_faq_cache_alias(question)
    retrieval_question = build_enterprise_faq_retrieval_question(
        question, direct_alias_category, direct_alias
    )
    request_threshold = (
        entity_fallback_threshold if entity_term else similarity_threshold
    )

    url = base_url + "/api/v1/retrieval"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 确保payload中的字符串都是UTF-8编码
    payload = {
        "schema_version": RAG_CACHE_SCHEMA_VERSION,
        "question": retrieval_question,
        "dataset_ids": dataset_ids,
        "page": 1,
        "page_size": page_size,
        "top_k": top_k,
        "similarity_threshold": request_threshold,
    }

    cache_key = _build_cache_key(
        base_url=base_url,
        question=question,
        dataset_ids=dataset_ids,
        page_size=page_size,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        entity_fallback_threshold=entity_fallback_threshold,
        max_context_chunks=max_context_chunks,
        max_context_chars=max_context_chars,
        direct_answer_enabled=direct_answer_enabled,
        direct_answer_min_similarity=direct_answer_min_similarity,
        direct_answer_min_support=direct_answer_min_support,
        direct_answer_score_gap=direct_answer_score_gap,
        direct_answer_max_chars=direct_answer_max_chars,
        retrieval_question=retrieval_question,
    )
    direct_alias_cache_key = ""
    if direct_answer_enabled and direct_alias_cache_enabled and direct_alias:
        direct_alias_cache_key = _build_direct_alias_cache_key(
            base_url=base_url,
            dataset_ids=dataset_ids,
            alias=direct_alias,
            page_size=page_size,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            entity_fallback_threshold=entity_fallback_threshold,
            direct_answer_min_similarity=direct_answer_min_similarity,
            direct_answer_min_support=direct_answer_min_support,
            direct_answer_score_gap=direct_answer_score_gap,
            direct_answer_max_chars=direct_answer_max_chars,
            retrieval_question=retrieval_question,
        )
    if cache_enabled and cache_ttl > 0:
        if direct_alias_cache_key:
            cached_direct_answer = cache_manager.get(
                CacheType.RAGFLOW,
                direct_alias_cache_key,
                namespace=DIRECT_ANSWER_ALIAS_CACHE_NAMESPACE,
            )
            logger.bind(tag=TAG).info(
                "LATENCY event=ragflow_direct_alias_cache hit={} category={} ttl={}",
                cached_direct_answer is not None,
                direct_alias_category,
                cache_ttl,
            )
            if cached_direct_answer:
                return ActionResponse(Action.RESPONSE, None, cached_direct_answer)
        cached_context = cache_manager.get(CacheType.RAGFLOW, cache_key)
        if cached_context is not None:
            logger.bind(tag=TAG).info(
                "LATENCY event=ragflow_cache hit=true key={} ttl={}",
                cache_key[:12],
                cache_ttl,
            )
            if isinstance(cached_context, dict):
                cached_direct_answer = cached_context.get("direct_answer", "")
                if direct_answer_enabled and cached_direct_answer:
                    logger.bind(tag=TAG).info(
                        "LATENCY event=ragflow_direct_answer source=cache chars={}",
                        len(cached_direct_answer),
                    )
                    return ActionResponse(Action.RESPONSE, None, cached_direct_answer)
                cached_context = cached_context.get("context", "")
            return ActionResponse(Action.REQLLM, cached_context, None)

        logger.bind(tag=TAG).info(
            "LATENCY event=ragflow_cache hit=false key={} enabled={} ttl={}",
            cache_key[:12],
            cache_enabled,
            cache_ttl,
        )
    if retrieval_question != question:
        logger.bind(tag=TAG).info(
            "LATENCY event=ragflow_query_rewrite category={} query={}",
            direct_alias_category,
            retrieval_question,
        )

    try:
        start_time = time.monotonic()
        # Reuse a bounded pool to avoid TCP/TLS handshakes on every RAG query.
        response, connection_reused, retry_count = await ragflow_http_client_pool.post(
            url, json=payload, headers=headers
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.bind(tag=TAG).info(
            "LATENCY event=ragflow_retrieval dataset_count={} ms={} connection_reused={} retry_count={}",
            len(dataset_ids),
            elapsed_ms,
            connection_reused,
            retry_count,
        )

        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"

        response.raise_for_status()

        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text

        result = json.loads(response_text)

        if result.get("code") != 0:
            error_detail = result.get("error", {}).get("detail", "未知错误")
            error_message = result.get("error", {}).get("message", "")
            error_code = result.get("code", "")

            # 安全地记录错误信息
            logger.bind(tag=TAG).error(
                f"RAGFlow API调用失败，响应码：{error_code}，错误详情：{error_detail}，完整响应：{result}"
            )

            # 构建详细的错误响应
            error_response = f"RAG接口返回异常（错误码：{error_code}）"

            if error_message:
                error_response += f"：{error_message}"
            if error_detail:
                error_response += f"\n详情：{error_detail}"

            return ActionResponse(Action.RESPONSE, None, error_response)

        chunks = result.get("data", {}).get("chunks", [])
        if entity_term:
            raw_chunk_count = len(chunks)
            chunks = filter_contexts_containing_term(chunks, entity_term)
            logger.bind(tag=TAG).info(
                "LATENCY event=ragflow_entity_filter entity={} threshold={} raw_chunks={} matched_chunks={}",
                entity_term,
                request_threshold,
                raw_chunk_count,
                len(chunks),
            )
        direct_answer = ""
        if direct_answer_enabled:
            direct_answer = select_direct_qa_answer(
                question,
                chunks,
                min_similarity=direct_answer_min_similarity,
                min_support=direct_answer_min_support,
                min_score_gap=direct_answer_score_gap,
                max_chars=direct_answer_max_chars,
            )
            if not direct_answer and direct_alias_category == "org_address":
                direct_answer = select_enterprise_location_answer(
                    question,
                    chunks,
                    subject=_alias_subject(direct_alias),
                    min_similarity=request_threshold,
                    max_chars=direct_answer_max_chars,
                )
        contents = []
        for chunk in chunks:
            content = chunk.get("content", "")
            if content:
                # 安全地处理内容字符串
                if isinstance(content, str):
                    contents.append(content)
                elif isinstance(content, bytes):
                    contents.append(content.decode("utf-8", errors="replace"))
                else:
                    contents.append(str(content))

        context_contents, duplicate_count = select_rag_contexts(
            contents, max_context_chunks, max_context_chars
        )
        logger.bind(tag=TAG).info(
            "LATENCY event=ragflow_context chunks={} selected_chunks={} duplicate_answers={} selected_chars={} page_size={} top_k={} similarity_threshold={}",
            len(chunks),
            len(context_contents),
            duplicate_count,
            sum(len(content) for content in context_contents),
            page_size,
            top_k,
            request_threshold,
        )

        if not context_contents:
            return ActionResponse(
                Action.RESPONSE,
                None,
                "知识库里暂时没有这项信息。",
            )

        # 组织知识库内容为引用模式
        context_text = f"# 关于问题【{question}】查到知识库如下\n"
        context_text += "```\n\n\n".join(context_contents)
        context_text += "\n```"
        if cache_enabled and cache_ttl > 0:
            cache_manager.set(
                CacheType.RAGFLOW,
                cache_key,
                {"context": context_text, "direct_answer": direct_answer},
                ttl=cache_ttl,
            )
            if direct_answer and direct_alias_cache_key:
                cache_manager.set(
                    CacheType.RAGFLOW,
                    direct_alias_cache_key,
                    direct_answer,
                    ttl=cache_ttl,
                    namespace=DIRECT_ANSWER_ALIAS_CACHE_NAMESPACE,
                )
        if direct_answer:
            logger.bind(tag=TAG).info(
                "LATENCY event=ragflow_direct_answer source=retrieval chars={}",
                len(direct_answer),
            )
            return ActionResponse(Action.RESPONSE, None, direct_answer)
        configured_staged_reply = staged_first_reply
        staged_first_reply = ""
        staged_first_reply_source = "none"

        if not staged_first_reply and staged_first_reply_enabled and configured_staged_reply:
            staged_first_reply = configured_staged_reply
            staged_first_reply_source = "configured_fallback"
        logger.bind(tag=TAG).info(
            "LATENCY event=ragflow_staged_first_reply source={} chars={}",
            staged_first_reply_source,
            len(staged_first_reply or ""),
        )
        staged_first_reply = staged_first_reply or None
        return ActionResponse(Action.REQLLM, context_text, staged_first_reply)

    except httpx.TimeoutException as e:
        error_response = "RAG接口请求超时"
        error_response += "\n可能原因：RAGflow服务响应缓慢或网络延迟"
        error_response += "\n解决方案：请稍后重试或检查RAGflow服务性能"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except httpx.HTTPStatusError as e:
        if hasattr(e.response, "status_code"):
            status_code = e.response.status_code
            error_response = f"RAG接口HTTP错误（状态码：{status_code}）"
            try:
                error_detail = e.response.json().get("error", {}).get("message", "")
                if error_detail:
                    error_response += f"\n错误详情：{error_detail}"
            except:
                pass
        else:
            error_response = f"RAG接口HTTP异常：{str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except httpx.HTTPError as e:
        error_response = "无法连接到RAG接口"
        error_response += "\n可能原因：RAGflow服务地址错误或服务未运行"
        error_response += "\n解决方案：请检查RAGflow服务地址配置和服务状态"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except Exception as e:
        # 其他异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGflow处理异常，异常类型：{error_type}，详情：{str(e)}"
        )

        # 提供详细的错误信息
        error_response = f"RAG接口处理异常（{error_type}）：{str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)


def _get_int_config(config, key, default, min_value, max_value):
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _get_float_config(config, key, default, min_value, max_value):
    try:
        value = float(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(max_value, value))


def _get_bool_config(config, key, default):
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "否", "关闭"}
    return bool(value)


def _build_cache_key(
    base_url,
    question,
    dataset_ids,
    page_size,
    top_k,
    similarity_threshold,
    entity_fallback_threshold,
    max_context_chunks,
    max_context_chars,
    direct_answer_enabled,
    direct_answer_min_similarity,
    direct_answer_min_support,
    direct_answer_score_gap,
    direct_answer_max_chars,
    retrieval_question,
):
    normalized_question = _normalize_question(question)
    normalized_dataset_ids = _normalize_dataset_ids(dataset_ids)
    payload = {
        "schema_version": RAG_CACHE_SCHEMA_VERSION,
        "base_url": str(base_url or "").rstrip("/"),
        "question": normalized_question,
        "retrieval_question": _normalize_question(retrieval_question),
        "dataset_ids": normalized_dataset_ids,
        "page_size": page_size,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "entity_fallback_threshold": entity_fallback_threshold,
        "max_context_chunks": max_context_chunks,
        "max_context_chars": max_context_chars,
        "direct_answer_enabled": direct_answer_enabled,
        "direct_answer_min_similarity": direct_answer_min_similarity,
        "direct_answer_min_support": direct_answer_min_support,
        "direct_answer_score_gap": direct_answer_score_gap,
        "direct_answer_max_chars": direct_answer_max_chars,
    }
    raw_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _normalize_question(question):
    text = str(question or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ?？!！。.")


def _normalize_dataset_ids(dataset_ids):
    if isinstance(dataset_ids, str):
        dataset_ids = [item.strip() for item in dataset_ids.split(",") if item.strip()]
    elif not isinstance(dataset_ids, list):
        dataset_ids = [str(dataset_ids)] if dataset_ids else []
    return sorted(str(item).strip() for item in dataset_ids if str(item).strip())


def _build_direct_alias_cache_key(
    base_url,
    dataset_ids,
    alias,
    page_size,
    top_k,
    similarity_threshold,
    entity_fallback_threshold,
    direct_answer_min_similarity,
    direct_answer_min_support,
    direct_answer_score_gap,
    direct_answer_max_chars,
    retrieval_question,
):
    payload = {
        "schema_version": RAG_CACHE_SCHEMA_VERSION,
        "base_url": str(base_url or "").rstrip("/"),
        "dataset_ids": _normalize_dataset_ids(dataset_ids),
        "alias": str(alias or ""),
        "retrieval_question": _normalize_question(retrieval_question),
        "page_size": page_size,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "entity_fallback_threshold": entity_fallback_threshold,
        "direct_answer_min_similarity": direct_answer_min_similarity,
        "direct_answer_min_support": direct_answer_min_support,
        "direct_answer_score_gap": direct_answer_score_gap,
        "direct_answer_max_chars": direct_answer_max_chars,
    }
    raw_key = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _alias_subject(alias):
    parts = str(alias or "").split(":")
    return parts[1] if len(parts) >= 2 else ""

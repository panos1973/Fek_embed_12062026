"""voyage_embed.py — contextualized embeddings + rerank (voyage-context-3 / rerank-2.5).

Whole-law nested input so each provision vector carries full-document context.
"""
from __future__ import annotations
import voyageai
import config

_client = None
MAX_TOKENS, MAX_CHUNKS, SAFETY = 120_000, 16_000, 0.9


def client():
    global _client
    if _client is None:
        config.require("VOYAGE_API_KEY")
        _client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    return _client


def _est_tokens(t: str) -> int:
    return max(1, len(t) // 3)


def embed_law_chunks(ordered_chunks: list[str]) -> list[list[float]]:
    if not ordered_chunks:
        return []
    budget = int(MAX_TOKENS * SAFETY)
    if (sum(_est_tokens(c) for c in ordered_chunks) <= budget
            and len(ordered_chunks) <= MAX_CHUNKS):
        r = client().contextualized_embed(inputs=[ordered_chunks],
                                          model=config.EMBED_MODEL,
                                          input_type="document",
                                          output_dimension=config.EMBED_DIM)
        return list(r.results[0].embeddings)
    out, span, tok = [], [], 0
    for c in ordered_chunks:
        t = _est_tokens(c)
        if span and (tok + t > budget or len(span) >= MAX_CHUNKS):
            r = client().contextualized_embed(inputs=[span], model=config.EMBED_MODEL,
                                              input_type="document",
                                              output_dimension=config.EMBED_DIM)
            out.extend(r.results[0].embeddings)
            span, tok = [], 0
        span.append(c); tok += t
    if span:
        r = client().contextualized_embed(inputs=[span], model=config.EMBED_MODEL,
                                          input_type="document",
                                          output_dimension=config.EMBED_DIM)
        out.extend(r.results[0].embeddings)
    return out


def embed_query(q: str) -> list[float]:
    r = client().contextualized_embed(inputs=[[q]], model=config.EMBED_MODEL,
                                      input_type="query",
                                      output_dimension=config.EMBED_DIM)
    return list(r.results[0].embeddings[0])


def rerank(query: str, documents: list[str], top_k: int | None = None,
           instruction: str | None = None) -> list[tuple[int, float]]:
    if not documents:
        return []
    q = f"{instruction}\n{query}" if instruction else query
    r = client().rerank(query=q, documents=documents, model=config.RERANK_MODEL,
                        top_k=top_k, truncation=True)
    return [(x.index, x.relevance_score) for x in r.results]

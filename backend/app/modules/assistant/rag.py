"""База знаний: чанкинг, индексация, гибридный поиск.

Гибридный поиск обязателен: на базе в полсотни документов чистый вектор
регулярно промахивается мимо точных формулировок («пункт 4.2», «форма 26»).
Вектор и полнотекст объединяются через Reciprocal Rank Fusion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import KbChunk, KbDocument
from app.modules.assistant.llm import get_llm

log = logging.getLogger("assistant.rag")

CHUNK_TARGET = 700
CHUNK_OVERLAP = 100
RRF_K = 60


@dataclass
class Fragment:
    chunk_id: int
    document_id: int
    title: str
    source_url: str
    text: str
    score: float


def chunk_text(body: str) -> list[str]:
    """Режем по абзацам, добираем до целевого размера, добавляем перекрытие."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    buf = ""

    for para in paragraphs:
        if len(buf) + len(para) + 2 <= CHUNK_TARGET:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) <= CHUNK_TARGET:
                buf = para
            else:
                # длинный абзац режем по предложениям
                sentences = re.split(r"(?<=[.!?])\s+", para)
                cur = ""
                for sent in sentences:
                    if len(cur) + len(sent) + 1 <= CHUNK_TARGET:
                        cur = f"{cur} {sent}".strip()
                    else:
                        if cur:
                            chunks.append(cur)
                        cur = sent
                buf = cur
    if buf:
        chunks.append(buf)

    if CHUNK_OVERLAP > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:], strict=False):
            tail = prev[-CHUNK_OVERLAP:]
            overlapped.append(f"{tail}\n{cur}")
        return overlapped
    return chunks


async def index_document(session: AsyncSession, doc: KbDocument) -> int:
    """Пересобирает чанки документа и считает эмбеддинги."""
    existing = await session.execute(select(KbChunk).where(KbChunk.document_id == doc.id))
    for old in existing.scalars():
        await session.delete(old)
    await session.flush()

    pieces = chunk_text(doc.body)
    if not pieces:
        return 0

    vectors: list[list[float] | None] = [None] * len(pieces)
    if settings.llm_enabled:
        try:
            vectors = await get_llm().embed(pieces, is_query=False)  # type: ignore[assignment]
        except Exception:
            log.warning("Эмбеддинги недоступны, документ «%s» проиндексирован "
                        "только для полнотекстового поиска", doc.title)

    for i, piece in enumerate(pieces):
        session.add(
            KbChunk(
                document_id=doc.id,
                ord=i,
                text=piece,
                embedding=vectors[i] if i < len(vectors) else None,
            )
        )
    await session.flush()
    return len(pieces)


async def reindex_all(session: AsyncSession) -> int:
    res = await session.execute(select(KbDocument).where(KbDocument.active.is_(True)))
    total = 0
    for doc in res.scalars():
        total += await index_document(session, doc)
    log.info("Переиндексировано чанков: %s", total)
    return total


async def _vector_hits(session: AsyncSession, query: str, limit: int) -> list[int]:
    if not settings.llm_enabled:
        return []
    try:
        vec = (await get_llm().embed([query], is_query=True))[0]
    except Exception:
        log.warning("Не удалось получить эмбеддинг запроса, остаётся полнотекст")
        return []
    if not vec:
        return []

    literal = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
    rows = await session.execute(
        text(
            "SELECT id FROM kb_chunk WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :lim"
        ),
        {"vec": literal, "lim": limit},
    )
    return [r[0] for r in rows]


async def _fulltext_hits(session: AsyncSession, query: str, limit: int) -> list[int]:
    rows = await session.execute(
        text(
            "SELECT id FROM kb_chunk "
            "WHERE to_tsvector('russian', text) @@ plainto_tsquery('russian', :q) "
            "ORDER BY ts_rank(to_tsvector('russian', text), "
            "                 plainto_tsquery('russian', :q)) DESC "
            "LIMIT :lim"
        ),
        {"q": query, "lim": limit},
    )
    return [r[0] for r in rows]


async def search(session: AsyncSession, query: str, top_k: int | None = None) -> list[Fragment]:
    """Гибридный поиск: вектор + полнотекст, объединение через RRF."""
    top_k = top_k or settings.RAG_TOP_K
    pool = max(top_k * 6, 30)

    vec_ids = await _vector_hits(session, query, pool)
    fts_ids = await _fulltext_hits(session, query, pool)

    scores: dict[int, float] = {}
    for rank, cid in enumerate(vec_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    for rank, cid in enumerate(fts_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)

    if not scores:
        return []

    best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    ids = [cid for cid, _ in best]

    res = await session.execute(
        select(KbChunk, KbDocument)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(KbChunk.id.in_(ids))
    )
    by_id = {chunk.id: (chunk, doc) for chunk, doc in res.all()}

    fragments: list[Fragment] = []
    for cid, score in best:
        pair = by_id.get(cid)
        if not pair:
            continue
        chunk, doc = pair
        fragments.append(
            Fragment(
                chunk_id=chunk.id,
                document_id=doc.id,
                title=doc.title,
                source_url=doc.source_url,
                text=chunk.text,
                score=score,
            )
        )
    return fragments


def format_fragments(fragments: list[Fragment]) -> str:
    """Собирает блок для системного сообщения."""
    if not fragments:
        return "В базе знаний ничего не нашлось по этому вопросу."
    parts = []
    for i, f in enumerate(fragments, start=1):
        parts.append(f"[Источник {i}: {f.title}]\n{f.text}")
    return "\n\n".join(parts)

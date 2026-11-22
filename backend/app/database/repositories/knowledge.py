"""Knowledge base (RAG) storage and retrieval.

Retrieval is lexical TF-IDF over short chunks, computed in Python. That is dependency-free,
works on PostgreSQL and SQLite, and is plenty for a curated knowledge base of a few hundred
chunks. To scale up, swap `search()` for pgvector / Postgres full-text search -- the tool
that calls it does not need to change.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeChunk, KnowledgeDocument, ServiceDirectoryEntry

# \w alone splits Indic words at vowel signs/viraamas (combining marks aren't "word" characters),
# so also accept the whole Indic Unicode range U+0900-U+0DFF.
_WORD = re.compile(r"[\wऀ-෿]+", re.UNICODE)
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "how", "what", "do", "i",
    "can", "my", "me", "with", "at", "by", "it", "this", "that", "from", "as", "under", "who", "which",
}


def _stem(t: str) -> str:
    """Very light English stemming so 'vaccines' matches 'vaccine' and 'pregnant' people find 'pregnancy' (Indic words are left alone)."""
    if not t.isascii() or len(t) < 5:
        return t
    for suffix, repl in (("ies", "y"), ("ing", ""), ("es", ""), ("ed", ""), ("s", "")):
        if t.endswith(suffix) and not t.endswith("ss") and len(t) - len(suffix) >= 3:
            return t[: -len(suffix)] + repl
    return t


# Everyday words people actually say -> the words the knowledge base uses. Applied to the QUESTION only.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "sugar": ("diabetes",), "diabetic": ("diabetes",), "bp": ("blood", "pressure", "hypertension"), "pressure": ("hypertension",),
    "pregnant": ("pregnancy",), "delivery": ("pregnancy", "newborn"), "baby": ("newborn", "child"), "infant": ("newborn", "child"),
    "injection": ("vaccine", "immunisation"), "vaccination": ("vaccine", "immunisation"), "vaccine": ("immunisation",), "shot": ("vaccine",),
    "immunization": ("immunisation",), "cough": ("tuberculosis",), "tb": ("tuberculosis",), "loose": ("diarrhoea",), "motions": ("diarrhoea",),
    "diarrhea": ("diarrhoea",), "temperature": ("fever",), "bukhar": ("fever",), "dawai": ("medicines",), "medicine": ("medicines", "jan", "aushadhi"),
    "cheap": ("low-cost", "generic"), "insurance": ("ayushman", "pmjay"), "stress": ("mental", "health"),
    "depression": ("mental", "health"), "anxiety": ("mental", "health"), "suicide": ("mental", "health", "tele-manas"), "ambulance": ("emergency", "108"),
    "police": ("emergency", "112"), "doctor": ("teleconsultation", "esanjeevani"), "online": ("teleconsultation", "esanjeevani"),
    "id": ("abha",), "health id": ("abha",), "snake": ("snakebite",), "burn": ("burns",), "burnt": ("burns",), "heat": ("heatstroke",),
    "anemia": ("anaemia",), "weak": ("anaemia",), "tired": ("anaemia",), "pale": ("anaemia",), "haemoglobin": ("anaemia",), "hemoglobin": ("anaemia",), "dengue": ("mosquito",), "malaria": ("mosquito",),
}


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


def expand_query(text: str) -> list[str]:
    raw = [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]
    extra = [w for t in raw for w in _SYNONYMS.get(t, ())]
    return [_stem(t) for t in raw + extra]


def chunk_text(text: str, max_chars: int = 700) -> list[str]:
    """Split on paragraph boundaries, packing paragraphs up to ~max_chars."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}".strip()
    if current:
        chunks.append(current)
    return chunks


@dataclass
class KnowledgeHit:
    title: str
    category: str
    text: str
    source_url: str | None
    score: float


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_empty(self) -> bool:
        return (await self.session.execute(select(func.count()).select_from(KnowledgeDocument))).scalar_one() == 0

    async def titles(self) -> set[str]:
        return set((await self.session.execute(select(KnowledgeDocument.title))).scalars().all())

    async def add_document(self, *, title: str, content: str, category: str = "general", language: str = "en", source_url: str | None = None) -> KnowledgeDocument:
        doc = KnowledgeDocument(title=title, category=category, language=language, source_url=source_url)
        doc.chunks = [KnowledgeChunk(chunk_index=i, text=t) for i, t in enumerate(chunk_text(content))]
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def search(self, query: str, top_k: int = 3, min_score: float = 0.0) -> list[KnowledgeHit]:
        q_tokens = expand_query(query)
        if not q_tokens:
            return []
        rows = (
            await self.session.execute(
                select(KnowledgeChunk, KnowledgeDocument).join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            )
        ).all()
        if not rows:
            return []

        docs_tokens = [tokenize(f"{d.title} {d.title} {c.text}") for c, d in rows]  # title counted twice = boost
        n = len(rows)
        df: Counter[str] = Counter()
        for toks in docs_tokens:
            df.update(set(toks))

        scored: list[tuple[float, int]] = []
        for i, toks in enumerate(docs_tokens):
            if not toks:
                continue
            tf = Counter(toks)
            score = 0.0
            for t in set(q_tokens):
                if t in tf:
                    idf = math.log(1 + n / (1 + df[t]))
                    score += (1 + math.log(tf[t])) * idf
            if score > 0:
                scored.append((score / math.sqrt(len(toks)), i))
        scored.sort(reverse=True)
        return [
            KnowledgeHit(title=rows[i][1].title, category=rows[i][1].category, text=rows[i][0].text, source_url=rows[i][1].source_url, score=round(s, 4))
            for s, i in scored[:top_k]
            if s >= min_score
        ]


class DirectoryRepository:
    """Read-only, parameterised lookups over the service directory (the 'controlled DB access' tool)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_empty(self) -> bool:
        return (await self.session.execute(select(func.count()).select_from(ServiceDirectoryEntry))).scalar_one() == 0

    async def add(self, **fields) -> ServiceDirectoryEntry:
        entry = ServiceDirectoryEntry(**fields)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def categories(self) -> list[str]:
        rows = await self.session.execute(select(ServiceDirectoryEntry.category).distinct().order_by(ServiceDirectoryEntry.category))
        return [r[0] for r in rows.all()]

    async def search(self, *, category: str | None, query: str | None, state: str | None, limit: int = 8) -> list[ServiceDirectoryEntry]:
        stmt = select(ServiceDirectoryEntry)
        if category:
            stmt = stmt.where(ServiceDirectoryEntry.category == category)
        if state:
            stmt = stmt.where((ServiceDirectoryEntry.state.is_(None)) | (func.lower(ServiceDirectoryEntry.state) == state.lower()))
        rows = list((await self.session.execute(stmt.order_by(ServiceDirectoryEntry.name))).scalars().all())
        if query:
            q = set(tokenize(query))
            if q:
                def rank(e: ServiceDirectoryEntry) -> int:
                    return len(q & set(tokenize(f"{e.name} {e.description} {e.category}")))

                ranked = sorted(((rank(e), e) for e in rows), key=lambda t: -t[0])
                rows = [e for r, e in ranked if r > 0]
        return rows[:limit]

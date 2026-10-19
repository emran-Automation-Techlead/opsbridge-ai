"""Lexical retrieval over the knowledge base: BM25 ranking plus an interpretable 'coverage' score used for abstention.

Why lexical and not a vector database? This baseline is deterministic, free and explainable, which is what the tests and the
evaluation need. The Retriever interface (search -> chunks with scores) is where a vector store (Chroma, pgvector, OpenSearch) would plug in.
That is NOT implemented here and is listed as a limitation.

coverage(chunk, question) = sum(idf of question terms found in the chunk) / sum(idf of all question terms).
Terms the corpus has never seen get the highest idf, so out-of-domain questions score low and the system abstains.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import config

STOP = {"a", "an", "the", "of", "to", "for", "in", "on", "at", "by", "with", "and", "or", "but", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "there", "their", "they", "them", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "do", "does", "did", "can", "could", "should", "would", "must", "may", "might", "will", "shall", "i", "me", "my", "we", "our", "you", "your", "he", "she", "as", "from", "into", "than", "then", "so", "if", "not", "no", "yes", "about", "before", "after", "over", "under", "tell", "please"}


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    heading: str
    text: str
    tf: Counter = field(default_factory=Counter)
    length: int = 0


@dataclass
class Hit:
    chunk: Chunk
    bm25: float
    coverage: float


class Retriever:
    def __init__(self, kb_dir: Path | None = None):
        self.chunks: list[Chunk] = []
        for path in sorted(Path(kb_dir or config.KB_DIR).glob("*.md")):
            self._load(path)
        if not self.chunks:
            raise RuntimeError("knowledge base is empty")
        self.n = len(self.chunks)
        self.df: Counter = Counter()
        for c in self.chunks:
            self.df.update(c.tf.keys())
        self.avgdl = sum(c.length for c in self.chunks) / self.n

    def _load(self, path: Path) -> None:
        doc_id = "-".join(path.stem.split("-")[:2])
        title, heading, buf = path.stem, "", []
        parts: list[tuple[str, str]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if buf:
                    parts.append((heading, " ".join(buf)))
                heading, buf = line[3:].strip(), []
            elif line.strip() and not line.startswith(">"):
                buf.append(line.strip())
        if buf:
            parts.append((heading, " ".join(buf)))
        for idx, (heading, body) in enumerate(parts, 1):
            toks = tokens(f"{title} {heading} {body}")
            self.chunks.append(Chunk(f"{doc_id}#{idx}", doc_id, title, heading, body, Counter(toks), len(toks)))

    def idf(self, term: str) -> float:
        return math.log((self.n + 1) / (self.df.get(term, 0) + 0.5)) + 1.0

    def coverage(self, chunk: Chunk, qterms: set[str]) -> float:
        total = sum(self.idf(t) for t in qterms)
        return sum(self.idf(t) for t in qterms if t in chunk.tf) / total if total else 0.0

    def search(self, question: str, k: int | None = None) -> list[Hit]:
        qterms = set(tokens(question))
        if not qterms:
            return []
        k1, b = 1.5, 0.75
        hits = []
        for c in self.chunks:
            s = 0.0
            for t in qterms:
                f = c.tf.get(t, 0)
                if f:
                    s += self.idf(t) * f * (k1 + 1) / (f + k1 * (1 - b + b * c.length / self.avgdl))
            hits.append(Hit(c, round(s, 4), round(self.coverage(c, qterms), 4)))
        hits.sort(key=lambda h: (h.bm25, h.coverage), reverse=True)
        return hits[: (k or config.TOP_K)]

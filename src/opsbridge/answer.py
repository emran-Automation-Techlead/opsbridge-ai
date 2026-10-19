"""Grounded question answering with citations and abstention."""
from __future__ import annotations

import re

from . import audit, config
from .models import Answer, Citation
from .providers import ExtractiveProvider, Provider
from .retrieval import Retriever, tokens
from .tracing import Trace

ABSTAIN_TEXT = "I do not have enough evidence in the policy knowledge base to answer that."
_default_retriever: Retriever | None = None


def _retriever() -> Retriever:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = Retriever()
    return _default_retriever


def _best_sentences(text: str, qterms: set[str], n: int = 2) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scored = [(len(qterms & set(tokens(s))), i, s) for i, s in enumerate(sents)]
    chosen = sorted(sorted(scored, key=lambda x: (-x[0], x[1]))[:n], key=lambda x: x[1])
    chosen = [c for c in chosen if c[0] > 0] or [(0, 0, sents[0])]
    return " ".join(s for _, _, s in chosen)


def ask(question: str, retriever: Retriever | None = None, provider: Provider | None = None, actor: str = "user") -> Answer:
    retriever = retriever or _retriever()
    provider = provider or ExtractiveProvider()
    trace = Trace("ask")
    with trace.span("retrieve", question=question):
        hits = retriever.search(question)
    top = hits[0] if hits else None
    confidence = top.coverage if top else 0.0
    if top is None or confidence < config.ABSTAIN_THRESHOLD:
        audit.write(trace.trace_id, actor, "ask", "abstained", question=question, confidence=confidence)
        trace.finish()
        return Answer(trace_id=trace.trace_id, question=question, answer=ABSTAIN_TEXT, abstained=True, confidence=confidence, provider=provider.name)

    qterms = set(tokens(question))
    used = [h for h in hits if h.coverage >= config.ABSTAIN_THRESHOLD][:2]
    citations = [Citation(doc_id=h.chunk.doc_id, chunk_id=h.chunk.chunk_id, title=h.chunk.title,
                          quote=_best_sentences(h.chunk.text, qterms)) for h in used]
    text, used_provider = " ".join(c.quote for c in citations[:1]), "extractive"
    with trace.span("compose", provider=provider.name):
        llm_text = provider.compose(question, [c.quote for c in citations])
    if llm_text:
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", llm_text)}
        if llm_text.strip() != "INSUFFICIENT" and cited and cited <= set(range(1, len(citations) + 1)):
            text, used_provider = llm_text, provider.name
        else:
            audit.write(trace.trace_id, "system", "llm_guard_fallback", "extractive_used", reason="uncited_or_unknown_source")
    audit.write(trace.trace_id, actor, "ask", "answered", question=question, confidence=confidence, sources=[c.chunk_id for c in citations])
    trace.finish()
    return Answer(trace_id=trace.trace_id, question=question, answer=text, abstained=False, confidence=confidence,
                  citations=citations, provider=used_provider)

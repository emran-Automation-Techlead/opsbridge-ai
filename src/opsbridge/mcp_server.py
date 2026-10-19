"""MCP server (stdio). Exposes ONLY read-only/low-risk capabilities to an AI client: ask a policy question, classify a document.
Approvals are deliberately NOT exposed: an AI agent must not be able to approve its own high-impact action.
Run:  python -m opsbridge.mcp_server      (requires the `mcp` package)"""
from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP  # mcp SDK 1.x
except ImportError:  # mcp SDK 2.x renamed it
    from mcp.server import MCPServer as FastMCP

from . import answer, classify

mcp = FastMCP("opsbridge")


@mcp.tool()
def ask_policy(question: str) -> dict:
    """Answer a policy question from the knowledge base with citations, or abstain."""
    return answer.ask(question, actor="mcp").model_dump(mode="json")


@mcp.tool()
def classify_document(text: str) -> dict:
    """Classify a request document and extract its fields. Does not run any workflow actions."""
    doc_type, score, margin = classify.classify(text)
    return {"doc_type": doc_type.value, "score": score, "margin": margin, "fields": classify.extract(text).model_dump(mode="json"),
            "suspicious": classify.is_suspicious(text)}


if __name__ == "__main__":
    mcp.run()

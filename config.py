"""config.py — central config + secrets for the ingestion pipeline.

Secrets come from environment variables (set them, or use a .env loaded by your
shell). Collection names match create_all_collections.py (the Jun2026 batch).
"""
from __future__ import annotations
import os

# --- Weaviate ---
WEAVIATE_URL = os.environ.get(
    "WEAVIATE_URL",
    "https://dxyeak9tnm4gp8raeh1g.c0.europe-west3.gcp.weaviate.cloud",
)
WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY", "")

# --- Voyage ---
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
EMBED_MODEL = "voyage-context-3"
EMBED_DIM = 1024
RERANK_MODEL = "rerank-2.5"

# --- Azure Document Intelligence (table pages) ---
AZURE_DI_ENDPOINT = os.environ.get("DI_ENDPOINT", "")
AZURE_DI_KEY = os.environ.get("DI_KEY", "")

# --- LLM for enrichment (summary / keywords / EUROVOC / ΔΚΝ) ---
# Provider-agnostic. Pick via LLM_PROVIDER + LLM_MODEL (or the Electron Settings UI).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")   # anthropic | deepseek | openai
LLM_MODEL = os.environ.get("LLM_MODEL", "")                  # blank -> provider default
LLM_THINKING = os.environ.get("LLM_THINKING", "off").lower() in ("on", "true", "1")
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "high")  # low|medium|high (DeepSeek, when thinking on)
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0"))

# sdk: which client. base_url: OpenAI-compatible endpoint (None = native). key: config attr.
PROVIDERS = {
    "anthropic": {"sdk": "anthropic", "base_url": None,
                  "key": "ANTHROPIC_API_KEY", "default_model": "claude-haiku-4-5"},
    "deepseek":  {"sdk": "openai",
                  "base_url": "https://api.deepseek.com",
                  "key": "DEEPSEEK_API_KEY", "default_model": "deepseek-v4-flash"},
    "openai":    {"sdk": "openai", "base_url": None,
                  "key": "OPENAI_API_KEY", "default_model": "gpt-4.1"},
}

# --- Tenancy ---
DEFAULT_TENANT = os.environ.get("JURISDICTION", "gr")

# --- Collection names (must match create_all_collections.py) ---
FLAT_COLLECTION = "Jun2026GRLegaDocs"
GRAPH_DOCUMENT = "Jun2026LawDocument"
GRAPH_ARTICLE = "Jun2026LawArticle"
GRAPH_AMENDMENT = "Jun2026Amendment"
GRAPH_DELEGATION = "Jun2026Delegation"

# --- Local state DB ---
STATE_DB = os.environ.get("STATE_DB", "lawgic_state.db")

# --- Pipeline tuning ---
CONCURRENCY = int(os.environ.get("CONCURRENCY", "4"))


def require(*names: str) -> None:
    """Fail fast if required secrets are missing."""
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)}")

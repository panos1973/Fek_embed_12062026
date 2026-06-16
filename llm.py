"""llm.py — one call, three providers (Claude · DeepSeek V4 · OpenAI GPT-4.1).

Dispatch on config.LLM_PROVIDER. Claude uses the Anthropic SDK; DeepSeek and
OpenAI and DeepSeek use the OpenAI SDK (DeepSeek via its compatible endpoint).

CACHING NOTE: keep the SYSTEM prompt byte-identical across calls (stable prefix)
and put the variable per-provision text in the USER message (suffix). DeepSeek
caches repeated prefixes automatically and bills cache hits at a fraction of the
miss rate; Anthropic/OpenAI cache the prefix too. So the big instruction/schema
block is paid for once, then near-free on every subsequent provision.

THINKING: for summarization + metadata extraction, leave thinking OFF (set in
config). It's a bounded extraction task — chain-of-thought adds latency and billed
reasoning tokens without real quality gain. Reserve thinking for hard reasoning.
"""
from __future__ import annotations
import config

_client = None
_kind = None


def _ensure_client():
    global _client, _kind
    if _client is not None:
        return
    spec = config.PROVIDERS[config.LLM_PROVIDER]
    key = getattr(config, spec["key"], "")
    if not key:
        raise SystemExit(f"Missing {spec['key']} for LLM_PROVIDER={config.LLM_PROVIDER}")
    if spec["sdk"] == "anthropic":
        import anthropic
        _client = anthropic.Anthropic(api_key=key)
        _kind = "anthropic"
    else:
        from openai import OpenAI
        kw = {"api_key": key}
        if spec["base_url"]:
            kw["base_url"] = spec["base_url"]   # set for deepseek; omit for native OpenAI
        _client = OpenAI(**kw)
        _kind = "openai"


def model_name() -> str:
    spec = config.PROVIDERS[config.LLM_PROVIDER]
    return config.LLM_MODEL or spec["default_model"]


def complete(system: str, user: str, want_json: bool = True,
             max_tokens: int = 1024) -> str:
    """Return the model's text output. `system` should be the STABLE prefix."""
    _ensure_client()
    model = model_name()

    if _kind == "anthropic":
        kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}])
        if config.LLM_THINKING:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 2048}
            kwargs["temperature"] = 1.0          # required when thinking is on
        else:
            kwargs["temperature"] = config.LLM_TEMPERATURE
        msg = _client.messages.create(**kwargs)
        return "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")

    # openai SDK (openai gpt-4.1 / deepseek)
    kwargs = dict(model=model, max_tokens=max_tokens,
                  temperature=config.LLM_TEMPERATURE,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": user}])
    if want_json:
        kwargs["response_format"] = {"type": "json_object"}
    if config.LLM_PROVIDER == "deepseek":
        # DeepSeek V4: thinking is a per-request param; level via reasoning_effort.
        # Flash defaults non-thinking; Pro defaults thinking — so we set it explicitly.
        if config.LLM_THINKING:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            kwargs["reasoning_effort"] = config.LLM_REASONING_EFFORT
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = _client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""

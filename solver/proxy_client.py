"""LLM proxy client.

Two modes:
  1. live   — talks to the organizer's stdin/stdout JSON proxy at runtime.
              Solver does: print('{"call":"llm",...}') and reads the response
              from stdin. This is the Stage 2 Solo protocol.
  2. local  — for development / Karpathy loop. Talks to a local OpenAI-compatible
              endpoint (Ollama / vLLM / OpenRouter) running gpt-oss-20b or
              gemma-4-31B so we can run the bandit offline.

LAWFORGE_PROXY_MODE env var picks. Default: 'live' in solver.py runtime;
loop.sh exports 'local'.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    tokens: int = 0


def call_llm(prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> LLMResponse:
    mode = os.environ.get("LAWFORGE_PROXY_MODE", "live")
    if mode == "live":
        return _call_live(prompt, max_tokens, temperature)
    return call_local(prompt, max_tokens, temperature)


def _call_live(prompt: str, max_tokens: int, temperature: float) -> LLMResponse:
    """Stage 2 Solo protocol: ask the organizer's proxy via stdin/stdout."""
    req = {"call": "llm", "prompt": prompt,
           "max_tokens": max_tokens, "temperature": temperature}
    sys.stdout.write(json.dumps(req) + "\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        return LLMResponse(text="", tokens=0)
    resp = json.loads(line)
    return LLMResponse(text=resp.get("text", ""), tokens=resp.get("tokens", 0))


DEFAULT_LLM_TIMEOUT_S = 25.0
DEFAULT_LLM_URL = "http://localhost:11434/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-oss:20b"


def call_local(prompt: str, max_tokens: int, temperature: float) -> LLMResponse:
    """OpenAI-compatible endpoint client. Hard timeout via LAWFORGE_LLM_TIMEOUT
    (default 25s). No retry. The caller controls max_tokens — no silent cap."""
    import socket
    import urllib.request

    url = os.environ.get("LAWFORGE_LLM_URL", DEFAULT_LLM_URL)
    model = os.environ.get("LAWFORGE_LLM_MODEL", DEFAULT_LLM_MODEL)
    key = os.environ.get("LAWFORGE_LLM_KEY", "no-key")
    timeout = float(os.environ.get("LAWFORGE_LLM_TIMEOUT", str(DEFAULT_LLM_TIMEOUT_S)))
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return LLMResponse(text=text, tokens=tokens)
    except (socket.timeout, TimeoutError):
        return LLMResponse(text="# LLM timeout", tokens=0)
    except Exception as e:
        return LLMResponse(text=f"# LLM error: {type(e).__name__}: {e}", tokens=0)


def submit_judge(verdict: str, code: str) -> dict:
    """Stage 2 Solo: submit a candidate certificate to the judge via the proxy."""
    req = {"call": "judge", "verdict": verdict, "code": code}
    sys.stdout.write(json.dumps(req) + "\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        return {"status": "unparsed"}
    return json.loads(line)

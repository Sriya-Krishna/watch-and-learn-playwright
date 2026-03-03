"""
LLM abstraction layer — adapted from backend/server.py.
Key difference: returns raw text strings (not parsed JSON dicts),
since the Playwright service works with Python code, not just JSON.
"""

import json
import os

from config import LLM_PROVIDER

# Initialize the selected provider client
if LLM_PROVIDER == "openai":
    from openai import OpenAI
    client = OpenAI()
elif LLM_PROVIDER == "kimi":
    import httpx as _httpx
    NVIDIA_API_KEY = os.getenv("NVIDIA_API")
    NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
else:
    import anthropic
    client = anthropic.Anthropic()


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


def _call_anthropic(system: str, user_message: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return _strip_code_fences(response.content[0].text)


def _call_openai(system: str, user_message: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=8192,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    return _strip_code_fences(response.choices[0].message.content)


def _call_kimi(system: str, user_message: str) -> str:
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": "moonshotai/kimi-k2.5",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 16384,
        "temperature": 1.00,
        "top_p": 1.00,
        "stream": True,
        "chat_template_kwargs": {"thinking": True},
    }

    print(f"[Kimi] Calling NVIDIA API with model: {payload['model']}")
    content_parts = []
    with _httpx.stream("POST", NVIDIA_URL, headers=headers, json=payload, timeout=120) as response:
        response.raise_for_status()
        print(f"[Kimi] Stream connected — status {response.status_code}")
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = chunk["choices"][0].get("delta", {})
            if delta.get("content"):
                content_parts.append(delta["content"])
                print(f"[Kimi] Content chunk: {delta['content'][:80]}")

    full_content = "".join(content_parts)
    print(f"[Kimi] Response ({len(full_content)} chars): {full_content[:200]}...")
    return _strip_code_fences(full_content)


def call_llm(system: str, user_message: str, provider: str | None = None) -> str:
    """Call the configured LLM and return raw text response."""
    p = provider or LLM_PROVIDER
    if p == "openai":
        return _call_openai(system, user_message)
    if p == "kimi":
        return _call_kimi(system, user_message)
    return _call_anthropic(system, user_message)

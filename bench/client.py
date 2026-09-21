"""Timed llama.cpp chat-completion client (stdlib only).

Streams the response so time-to-first-token and total wall time are measured on
the client, and keeps the server-reported timings for prefill/decode attribution.
"""

import base64
import http.client
import json
import time
from urllib.parse import urlparse


def image_part(path):
    data = path.read_bytes()
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return {"type": "image_url", "image_url": {
        "url": f"data:{mime};base64," + base64.b64encode(data).decode()}}


def get_json(base_url, path, body=None, timeout=30):
    url = urlparse(base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    try:
        if body is None:
            conn.request("GET", path)
        else:
            conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        response = conn.getresponse()
        text = response.read().decode()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {text[:500]}")
        return json.loads(text)
    finally:
        conn.close()


def timed_chat(base_url, payload, timeout=600):
    """POST a streaming chat completion; return assembled message plus timings.

    Returned seconds are client-side wall clock from just before the request is
    sent: `ttft_s` is the first delta carrying content, reasoning, or a tool call;
    `first_call_s` is the first tool-call or content delta (excludes reasoning).
    """
    url = urlparse(base_url)
    body = json.dumps({**payload, "stream": True,
                       "stream_options": {"include_usage": True}}).encode()
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=timeout)
    content, reasoning, calls = [], [], {}
    finish, usage, timings = None, {}, {}
    ttft = first_call = None
    started = time.perf_counter()
    try:
        conn.request("POST", url.path.rstrip("/") + "/chat/completions", body,
                     {"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {response.read().decode()[:800]}")
        for raw in response:
            line = raw.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            chunk = json.loads(data)
            now = time.perf_counter() - started
            usage = chunk.get("usage") or usage
            timings = chunk.get("timings") or timings
            for choice in chunk.get("choices", []):
                delta = choice.get("delta", {})
                finish = choice.get("finish_reason") or finish
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    ttft = ttft if ttft is not None else now
                if delta.get("content"):
                    content.append(delta["content"])
                    ttft = ttft if ttft is not None else now
                    first_call = first_call if first_call is not None else now
                for call in delta.get("tool_calls") or []:
                    ttft = ttft if ttft is not None else now
                    first_call = first_call if first_call is not None else now
                    slot = calls.setdefault(call.get("index", 0), {"name": "", "arguments": ""})
                    fn = call.get("function", {})
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
        total = time.perf_counter() - started
    finally:
        conn.close()
    return {
        "content": "".join(content), "reasoning": "".join(reasoning),
        "tool_calls": [calls[index] for index in sorted(calls)],
        "finish_reason": finish, "usage": usage, "timings": timings,
        "total_s": total, "ttft_s": ttft, "first_call_s": first_call,
    }

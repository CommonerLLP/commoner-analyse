"""Shared SSRF-guarded HTTP POST helper for Ollama-compatible LLM endpoints.

``discourse.py`` (discourse-tier classification) and ``dossier.py``
(ministry-query refinement) each call an opt-in local/remote LLM over an
Ollama-compatible ``/chat/completions`` endpoint. Both need the same
endpoint-scheme validation, private-IP guard, and API-key resolution —
this module is the single copy of that logic.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
from typing import Any
from urllib import request as _url_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

# Schemes allowed for LLM endpoints. urllib.request.urlopen also honours
# file:// and ftp://, which would let a malicious topic-config string
# read local files; restrict to HTTP(S) only.
ALLOWED_LLM_SCHEMES = frozenset({"http", "https"})


def validate_llm_endpoint(endpoint: str, *, allow_private: bool = True) -> None:
    """Reject endpoint URLs that aren't HTTP(S) or that target unexpected hosts.

    The default ``allow_private=True`` exists because the LLM tier is
    designed for local Ollama (`http://localhost:11434/v1`). When the caller
    passes ``allow_private=False`` (e.g. for a hardened deployment), private
    IP ranges and link-local addresses are also blocked to defeat SSRF
    against internal services.

    Raises ``ValueError`` on invalid inputs; callers catch this and fall
    back to UNCLASSIFIED / an unresolved result for the affected record.
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in ALLOWED_LLM_SCHEMES:
        raise ValueError(
            f"LLM endpoint scheme must be one of {sorted(ALLOWED_LLM_SCHEMES)}; "
            f"got {parts.scheme!r}"
        )
    if not parts.hostname:
        raise ValueError("LLM endpoint URL has no hostname")
    if allow_private:
        return

    host = parts.hostname
    # First: is the host already an IP literal?
    # We separate the IP-literal parse from the rejection branch so
    # that our own "private/loopback rejected" ValueError is not
    # mistakenly caught by the surrounding try/except.
    ip_literal: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — host is a DNS name. Fall through to
        # name-based block + DNS resolution below.
        ip_literal = None

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    if ip_literal is not None:
        addrs = [ip_literal]
    else:
        # Block obvious loopback names without doing DNS first.
        if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
            raise ValueError(
                "LLM endpoint host is loopback; pass "
                "allow_private=True if intentional (e.g. local Ollama)."
            )
        # Resolve the hostname and check every returned address.
        # Without this, an attacker (or careless internal-DNS config)
        # could point a name at 10.0.0.x or 169.254.169.254 and
        # bypass --llm-block-private. We accept the latency cost on
        # the hardened path.
        try:
            resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(
                f"LLM endpoint host could not be resolved: {type(exc).__name__}"
            ) from exc
        seen: set[str] = set()
        for _family, _kind, _proto, _name, sockaddr in resolved:
            addr_str = sockaddr[0]
            if addr_str in seen:
                continue
            seen.add(addr_str)
            try:
                addrs.append(ipaddress.ip_address(addr_str))
            except ValueError:
                # Unrecognised address family — be conservative.
                raise ValueError(
                    "LLM endpoint host resolved to an unrecognised "
                    "address; refusing to dispatch."
                )

    for a in addrs:
        if (
            a.is_private
            or a.is_loopback
            or a.is_link_local
            or a.is_multicast
            or a.is_reserved
            or a.is_unspecified
        ):
            raise ValueError(
                "LLM endpoint host is private/loopback; pass "
                "allow_private=True if intentional (e.g. local Ollama)."
            )


def resolve_api_key(api_key: str | None) -> str | None:
    """Resolve ``env:VAR_NAME`` indirection; return None when no key set.

    Lets operators keep secrets in environment variables without putting
    them in topic-profile JSON (which is content-hashed and travels in
    ``_runs.jsonl``).
    """
    if not api_key:
        return None
    if api_key.startswith("env:"):
        return os.environ.get(api_key[4:])
    return api_key


def llm_http_post(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout_s: float,
    api_key: str | None = None,
    allow_private: bool = True,
) -> str:
    """POST to an Ollama-compatible chat completions endpoint; return raw content.

    Validates the endpoint scheme and (optionally) host privacy class before
    dispatching the request. Raises ``RuntimeError`` (caught upstream) on
    network failure; raises ``ValueError`` when the URL is rejected by the
    safety check.
    """
    validate_llm_endpoint(endpoint, allow_private=allow_private)
    base = endpoint.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resolved_key = resolve_api_key(api_key)
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"
    req = _url_request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with _url_request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"].get("content") or "{}"
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM endpoint unreachable: {type(exc).__name__}") from exc


def parse_llm_json(content: str) -> dict[str, Any]:
    """Parse JSON from LLM output; falls back to extracting the first
    balanced ``{...}`` block if the model wraps the JSON in markdown
    fences or prose.

    Uses ``json.JSONDecoder.raw_decode`` rather than a regex because
    neither a non-greedy ``\\{[^{}]*\\}`` (breaks on nested objects) nor
    a greedy ``\\{.*\\}`` (breaks on multiple objects, e.g. when the
    model outputs the answer plus a trailing example) is correct. The
    decoder walks JSON grammar properly: it returns the first valid
    JSON value starting at offset, then we ignore anything after.
    """
    decoder = json.JSONDecoder()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Find the first ``{`` and try raw_decode from there. If that
        # ``{`` is part of an unbalanced/garbage prefix, advance and
        # retry until success or end-of-input.
        for start in range(len(content)):
            if content[start] != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(content[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise

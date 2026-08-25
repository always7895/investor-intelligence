#!/usr/bin/env python3
"""Pure, injectable URL/DNS boundary for authoritative public fetches.

This module performs no network request by itself. Callers must validate the
initial URL and every redirect with a resolver that returns all A/AAAA answers.
Any private, loopback, link-local, reserved, multicast or unspecified answer
fails the whole request, preventing mixed-answer and DNS-rebinding bypasses.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence
from urllib.parse import unquote, urlsplit

Resolver = Callable[[str], Iterable[str]]


class PublicUrlError(ValueError):
    """Raised when a public source URL leaves a reviewed boundary."""


@dataclass(frozen=True)
class ReviewedUrlBoundary:
    hosts: tuple[str, ...]
    path_prefixes: tuple[str, ...] = ("/",)
    maximum_redirects: int = 3


def normalize_host(value: str) -> str:
    text = value.rstrip(".").strip()
    if not text:
        raise PublicUrlError("URL host is empty")
    try:
        return text.encode("idna").decode("ascii").casefold()
    except (UnicodeError, ValueError) as exc:
        raise PublicUrlError("URL host cannot be normalized") from exc


def _address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        return ipaddress.ip_address(value.strip().split("%", 1)[0])
    except ValueError as exc:
        raise PublicUrlError(f"Resolver returned a non-IP address: {value!r}") from exc


def address_is_public(value: str) -> bool:
    address = _address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _host_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    normalized_allowed = {normalize_host(value) for value in allowed_hosts}
    return host in normalized_allowed


def _path_allowed(path: str, prefixes: Sequence[str]) -> bool:
    decoded = unquote(path or "/")
    if "\x00" in decoded or "\\" in decoded:
        return False
    segments = []
    for value in decoded.split("/"):
        if value in ("", "."):
            continue
        if value == "..":
            return False
        segments.append(value)
    normalized = "/" + "/".join(segments)
    for prefix in prefixes:
        reviewed = "/" + "/".join(
            value for value in unquote(prefix or "/").split("/") if value not in ("", ".")
        )
        if reviewed == "/" or normalized == reviewed or normalized.startswith(reviewed + "/"):
            return True
    return False


def validate_public_url(
    url: str,
    boundary: ReviewedUrlBoundary,
    *,
    resolver: Resolver,
) -> str:
    try:
        parsed = urlsplit(str(url).strip())
        port = parsed.port
    except ValueError as exc:
        raise PublicUrlError("URL is malformed") from exc
    if parsed.scheme.casefold() != "https":
        raise PublicUrlError("Only HTTPS public URLs are allowed")
    if parsed.username or parsed.password:
        raise PublicUrlError("URL userinfo is forbidden")
    if port not in (None, 443):
        raise PublicUrlError("Non-443 public source ports are forbidden")
    host = normalize_host(parsed.hostname or "")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PublicUrlError("Public source hosts must not be IP literals")
    if not _host_allowed(host, boundary.hosts):
        raise PublicUrlError(f"Host {host!r} is outside the reviewed boundary")
    if not _path_allowed(parsed.path, boundary.path_prefixes):
        raise PublicUrlError("URL path is outside the reviewed boundary")
    answers = tuple(str(value).strip() for value in resolver(host) if str(value).strip())
    if not answers:
        raise PublicUrlError("Public source DNS returned no addresses")
    unsafe = [value for value in answers if not address_is_public(value)]
    if unsafe:
        raise PublicUrlError("Public source DNS includes a non-public address")
    return parsed.geturl()


def validate_redirect_chain(
    urls: Sequence[str],
    boundary: ReviewedUrlBoundary,
    *,
    resolver: Resolver,
) -> tuple[str, ...]:
    if not urls:
        raise PublicUrlError("Redirect chain is empty")
    redirects = len(urls) - 1
    if redirects > boundary.maximum_redirects:
        raise PublicUrlError("Redirect chain exceeds the reviewed limit")
    return tuple(validate_public_url(url, boundary, resolver=resolver) for url in urls)

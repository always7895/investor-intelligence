#!/usr/bin/env python3
"""Derive a Worker tenant hash locally without storing raw LINE identifiers.

Raw IDs and the HMAC secret are read from environment variables or hidden
interactive prompts. They are never printed, logged or written to disk. The
output is only the derived tenant hash used in Worker role allowlists/private
sync.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os


def required_secret(name: str, prompt: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    value = getpass.getpass(prompt).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def optional_secret(name: str, prompt: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value.strip()
    return getpass.getpass(prompt).strip()


def identity_material(
    source_type: str,
    *,
    user_id: str = "",
    group_id: str = "",
    room_id: str = "",
) -> str:
    normalized = source_type.strip().casefold()
    if normalized not in {"user", "group", "room"}:
        raise ValueError("source_type must be user, group or room")
    if not user_id:
        raise ValueError("user_id is required")
    if normalized == "group" and not group_id:
        raise ValueError("group_id is required for group source")
    if normalized == "room" and not room_id:
        raise ValueError("room_id is required for room source")
    return "|".join((normalized, user_id, group_id, room_id))


def derive_tenant_hash(material: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:43]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive a tenant HMAC hash without printing raw LINE IDs"
    )
    parser.add_argument("--source-type", choices=("user", "group", "room"), required=True)
    args = parser.parse_args()

    secret = required_secret("TENANT_HASH_SECRET", "TENANT_HASH_SECRET (hidden): ")
    user_id = required_secret("LINE_SOURCE_USER_ID", "LINE source user ID (hidden): ")
    group_id = (
        required_secret("LINE_SOURCE_GROUP_ID", "LINE source group ID (hidden): ")
        if args.source_type == "group"
        else ""
    )
    room_id = (
        required_secret("LINE_SOURCE_ROOM_ID", "LINE source room ID (hidden): ")
        if args.source_type == "room"
        else ""
    )

    material = identity_material(
        args.source_type,
        user_id=user_id,
        group_id=group_id,
        room_id=room_id,
    )
    print(derive_tenant_hash(material, secret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

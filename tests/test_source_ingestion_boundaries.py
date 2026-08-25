from __future__ import annotations

import gzip
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_payload_boundary import (  # noqa: E402
    PayloadLimits,
    SourcePayloadError,
    decode_payload,
    parse_bounded_json,
    validate_closed_object,
)


class SourceIngestionBoundaryTests(unittest.TestCase):
    def test_accepts_bounded_utf8_json_and_closed_schema(self) -> None:
        content = json.dumps({"series_id": "SYNTHETIC", "value": 1.5}).encode("utf-8")
        value = parse_bounded_json(content, content_type="application/json")
        validated = validate_closed_object(
            value,
            allowed_fields={"series_id", "value"},
            required_fields={"series_id", "value"},
            label="synthetic observation",
        )
        self.assertEqual(validated["value"], 1.5)

    def test_rejects_wire_and_decoded_byte_boundaries(self) -> None:
        limits = PayloadLimits(
            maximum_wire_bytes=16,
            maximum_decoded_bytes=32,
            maximum_decompression_ratio=10,
            maximum_json_depth=8,
            maximum_json_nodes=100,
        )
        with self.assertRaises(SourcePayloadError):
            decode_payload(b"x" * 17, content_encoding=None, limits=limits)

        compressed = gzip.compress(b"x" * 100)
        with self.assertRaises(SourcePayloadError):
            decode_payload(compressed, content_encoding="gzip", limits=limits)

    def test_rejects_gzip_bomb_ratio_and_unsupported_encoding(self) -> None:
        bomb = gzip.compress(b"A" * 100_000)
        limits = PayloadLimits(
            maximum_wire_bytes=1_000_000,
            maximum_decoded_bytes=1_000_000,
            maximum_decompression_ratio=5,
            maximum_json_depth=64,
            maximum_json_nodes=2_000_000,
        )
        with self.assertRaises(SourcePayloadError):
            decode_payload(bomb, content_encoding="gzip", limits=limits)
        with self.assertRaises(SourcePayloadError):
            decode_payload(b"content", content_encoding="br", limits=limits)

    def test_rejects_json_depth_node_count_nonfinite_and_wrong_type(self) -> None:
        deep: object = 1
        for _ in range(10):
            deep = [deep]
        limits = PayloadLimits(
            maximum_wire_bytes=100_000,
            maximum_decoded_bytes=100_000,
            maximum_decompression_ratio=50,
            maximum_json_depth=5,
            maximum_json_nodes=10_000,
        )
        with self.assertRaises(SourcePayloadError):
            parse_bounded_json(
                json.dumps(deep).encode(),
                content_type="application/json",
                limits=limits,
            )

        wide = list(range(100))
        node_limits = PayloadLimits(
            maximum_wire_bytes=100_000,
            maximum_decoded_bytes=100_000,
            maximum_decompression_ratio=50,
            maximum_json_depth=64,
            maximum_json_nodes=20,
        )
        with self.assertRaises(SourcePayloadError):
            parse_bounded_json(
                json.dumps(wide).encode(),
                content_type="application/json",
                limits=node_limits,
            )
        with self.assertRaises(SourcePayloadError):
            parse_bounded_json(b'{"value": NaN}', content_type="application/json")
        with self.assertRaises(SourcePayloadError):
            parse_bounded_json(b"{}", content_type="text/html")

    def test_schema_change_unknown_and_missing_fields_fail_closed(self) -> None:
        with self.assertRaises(SourcePayloadError):
            validate_closed_object(
                {"series_id": "SYNTHETIC", "value": 1, "new_private_field": 2},
                allowed_fields={"series_id", "value"},
                required_fields={"series_id", "value"},
                label="observation",
            )
        with self.assertRaises(SourcePayloadError):
            validate_closed_object(
                {"series_id": "SYNTHETIC"},
                allowed_fields={"series_id", "value"},
                required_fields={"series_id", "value"},
                label="observation",
            )

    def test_invalid_gzip_and_empty_payloads_fail_closed(self) -> None:
        with self.assertRaises(SourcePayloadError):
            decode_payload(b"not-gzip", content_encoding="gzip")
        with self.assertRaises(SourcePayloadError):
            decode_payload(b"", content_encoding=None)


if __name__ == "__main__":
    unittest.main()

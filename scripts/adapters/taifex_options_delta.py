"""Dataset 11321 only (DailyOptionsDelta): LOCAL_REFERENCE_ONLY contract/Delta reference rows, never quotes, never joined into the EOD rows.

The parsing contract lives in taifex_contract (delta_reference_rows: the bounded raw-bytes decoder; delta_reference_records: the closed
all-or-nothing row parser), shared with the manual importer. No as-of date, session, currency, multiplier, underlying, DTE, unit or sign
convention is advertised or inferred; the response shape is UNVERIFIED and an unsupported payload refuses the whole batch with a fixed
TAIFEX_DELTA_* code. The shared adapter base (json_document) is deliberately NOT used: it decodes arbitrary depth before any shape check.
This adapter is registered only in the staged (local) registry: it has no evidence builder, is not in the reviewed runtime registry or any
source registry, and nothing here is a publication or LINE quote approval.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .base import AdapterError, ParsedBatch, make_batch
from taifex_contract import (TAIFEX_DELTA_ENVELOPE, TAIFEX_DELTA_MAX_OUTPUT_BYTES, TAIFEX_DELTA_URL, delta_reference_records,
                             delta_reference_rows)  # envelope and output budget are re-exported to the collector

SOURCE = 'taifex_options_delta'
TAIFEX_DELTA_FEEDS = {SOURCE: TAIFEX_DELTA_URL}


class TaifexOptionsDeltaAdapter:
    source_id = SOURCE
    parser_version = 'taifex-options-delta-v1'

    def parse(self, content: bytes, *, content_type: str, retrieved_at: str,
              context: Mapping[str, Any]) -> ParsedBatch:
        try:
            records = delta_reference_records(delta_reference_rows(content), origin_verification='COLLECTOR_CAPTURE_UNQUALIFIED')
        except (ValueError, TypeError, OverflowError, ArithmeticError) as exc:
            code = str(exc)
            # All-or-nothing batch, fixed code only: no raw provider values or exception text.
            raise AdapterError(code if re.fullmatch(r'TAIFEX_DELTA_[A-Z_]+', code) else 'TAIFEX_DELTA_INVALID_VALUE') from None
        # Mixed-source collector output carries no other attribution of a row, so each row names its own source.
        records = [{'source_id': SOURCE, **record} for record in records]
        return make_batch(source_id=SOURCE, parser_version=self.parser_version, content=content,
                          retrieved_at=retrieved_at, records=records)


TAIFEX_DELTA_ADAPTERS = {SOURCE: TaifexOptionsDeltaAdapter()}

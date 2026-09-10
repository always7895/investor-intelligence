"""Malformed evidence timestamps must not become valid date-prefix evidence."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_v213_activation_bundle_v2 as builder
import v213_build_v21_public_snapshot as snapshot


class ActivationEvidenceTimestampTests(unittest.TestCase):
    def test_date_precision_and_valid_iso_are_preserved(self):
        self.assertEqual(builder._timestamp('2026-09-09', 'synthetic'),
                         datetime(2026, 9, 9, tzinfo=timezone.utc))
        self.assertEqual(builder._timestamp('2026-09-09T08:00:00+08:00', 'synthetic'),
                         datetime(2026, 9, 9, tzinfo=timezone.utc))

    def test_malformed_suffix_and_invalid_time_are_not_truncated(self):
        for value in ('2026-09-09NOT_A_TIMESTAMP', '2026-09-09T99:00:00Z',
                      '2026-09-09T12:00:00+99:00', '2026-09-09T00:00:00Z trailing'):
            with self.subTest(value=value), self.assertRaises(builder.SerenityEvidenceError):
                builder._timestamp(value, 'synthetic')

    def test_pre_snapshot_support_does_not_admit_corrupt_dates(self):
        audit = builder._synthetic_documents()[-1]['records'][0]
        now = datetime.now(timezone.utc)
        self.assertTrue(snapshot._fresh_claim_support(audit, now=now, maximum_age_days=30)['supported'])
        for source in audit['sources']:
            source['as_of'] = source['as_of'][:10] + 'NOT_A_TIMESTAMP'
        support = snapshot._fresh_claim_support(audit, now=now, maximum_age_days=30)
        self.assertFalse(support['supported'])
        self.assertEqual(support['unit_count'], 0)

    def test_actual_bundle_builder_rejects_corrupt_source_dates(self):
        documents = builder._synthetic_documents()
        self.assertIn('payloads', builder.build_bundle(*documents))
        for source in documents[-1]['records'][0]['sources']:
            source['as_of'] = source['as_of'][:10] + 'NOT_A_TIMESTAMP'
        with self.assertRaises(builder.SerenityEvidenceError):
            builder.build_bundle(*documents)


if __name__ == '__main__':
    unittest.main()

"""Synthetic, fixed-clock claim reconciliation; never qualifies live sources."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import source_observation as observations
from source_registry import Registry, SourceDefinition
import v213_source_independence_gate as core
import v213_source_independence_gate_v4 as wrapper

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
STAMP = '2026-09-12T12:00:00Z'


def source(name, authority, tier, roles):
    return SourceDefinition(
        source_id=name, display_name=name, authority_class=authority, trust_tier=tier,
        evidence_roles=tuple(roles), jurisdictions=('US',), languages=('en',),
        canonical_urls=(f'https://{name}.example/',), independence_group=name,
        admission_status='RUNTIME_ENABLED', adapter_id=name, adapter_status='tested',
        runtime_enabled=True, free_access_required=True, payment_required=False,
        terms_review_status='reviewed', priority=1, per_host_concurrency=1,
        minimum_request_interval_seconds=1, maximum_retries=0,
        freshness_seconds=400 * 86400, correction_tracking=True,
        provenance_required=True, notes='synthetic fixture only', catalog_file='fixture')


REGISTRY = Registry(1, (
    source('issuer', 'securities_regulator', 'T1_PRIMARY_OFFICIAL', ['financial_statements']),
    source('news', 'reputable_newswire', 'T2_INSTITUTIONAL_CORROBORATION', ['financial_reporting', 'industry_research']),
    source('news-two', 'reputable_newswire', 'T2_INSTITUTIONAL_CORROBORATION', ['financial_reporting', 'industry_research']),
    source('exchange', 'regulated_exchange', 'T1_PRIMARY_OFFICIAL', ['market_data']),
    source('macro', 'national_statistics_office', 'T1_PRIMARY_OFFICIAL', ['economic_data']),
    source('yahoo-like', 'reputable_financial_media', 'T3_REPUTABLE_SECONDARY_LEAD', ['financial_reporting']),
), ())


def claim(name='revenue', kind='issuer_financial_statement'):
    return dict(claim_id=name, claim_type=kind, subject='SYN', metric=name,
                period='2026Q2', unit='million', currency='USD', basis='GAAP', scope='consolidated')


def evidence(name='issuer', cid='revenue', kind='issuer_financial_statement', value=100):
    role = REGISTRY.by_id()[name].evidence_roles[0]
    return dict(source_id=name, canonical_url=f'https://{name}.example/report',
                published_at=STAMP, retrieved_at='2026-09-13T11:00:00Z',
                content_sha256=(format(list(REGISTRY.by_id()).index(name) + 1, 'x') * 64),
                parser_id=name, parser_version='1', jurisdiction='US', language='en',
                claim_type=kind, evidence_role=role, source_health='HEALTHY',
                payload=dict(claim_ids=[cid], subject='SYN', metric=cid,
                             period='2026Q2', unit='million', currency='USD', value=value,
                             basis='GAAP', scope='consolidated',
                             as_of=STAMP, passage='Synthetic disclosed value, not live evidence.',
                             origin_group=name))


def document(rows=None, claims=None):
    return dict(material_claims=[claim()] if claims is None else claims,
                source_observations=[evidence(), evidence('news')] if rows is None else rows)


def assess(doc):
    return observations.reconcile_research_claims(doc, registry=REGISTRY, now=NOW,
                                                 health_states={key: 'HEALTHY' for key in REGISTRY.by_id()})


class ResearchClaimTests(unittest.TestCase):
    def test_two_independent_exact_claim_sources_supported(self):
        result = assess(document())
        row = result['claims'][0]
        self.assertEqual(row['status'], 'SUPPORTED')
        self.assertEqual(row['independent_evidence_families'], 2)
        self.assertTrue(row['high_confidence_eligible'])
        for key in ('url', 'domain', 'source_class', 'publisher', 'published_at', 'retrieved_at', 'primary', 'independence_group', 'claim_ids', 'freshness', 'confidence'):
            self.assertIn(key, result['evidence'][0])

    def test_one_document_can_support_multiple_separate_claims(self):
        rows = [evidence(), evidence('news'), evidence(cid='net_income', value=20), evidence('news', 'net_income', value=20)]
        result = assess(document(rows, [claim(), claim('net_income')]))
        self.assertTrue(result['all_material_claims_supported'])
        self.assertEqual(len(result['evidence']), 4)

    def test_conflicting_parses_of_same_document_must_not_overwrite_each_other(self):
        result = assess(document([evidence(value=100), evidence(value=120), evidence('news', value=120)]))
        self.assertEqual(result['claims'][0]['status'], 'CONFLICTED')
        self.assertEqual(len(result['claims'][0]['conflict_set']), 3)

    def test_saved_degradation_cannot_soften_current_quarantine(self):
        doc = document()
        doc['source_observations'][0]['source_health'] = 'DEGRADED'
        result = observations.reconcile_research_claims(doc, registry=REGISTRY, now=NOW,
            health_states={'issuer': 'QUARANTINED', 'news': 'HEALTHY'})
        self.assertEqual(result['rejected_observation_count'], 1)
        self.assertFalse(result['all_material_claims_supported'])

    def test_unrelated_claims_cannot_be_pooled(self):
        result = assess(document([evidence(), evidence('news', 'guidance')], [claim(), claim('guidance')]))
        self.assertFalse(result['all_material_claims_supported'])
        self.assertFalse(any(row['high_confidence_eligible'] for row in result['claims']))

    def test_syndicated_copies_same_origin_or_hash_count_once(self):
        for mechanism in ('origin_group', 'hash'):
            first, second = evidence(), evidence('news')
            if mechanism == 'origin_group':
                second['payload']['origin_group'] = first['payload']['origin_group']
            else:
                second['content_sha256'] = first['content_sha256']
            row = assess(document([first, second]))['claims'][0]
            self.assertEqual(row['independent_evidence_families'], 1)
            self.assertEqual(row['status'], 'SINGLE_SOURCE')
            self.assertLessEqual(row['confidence'], 0.49)

    def test_missing_lineage_does_not_invent_second_witness(self):
        second = evidence('news')
        del second['payload']['origin_group']
        result = assess(document([evidence(), second]))
        self.assertEqual(result['claims'][0]['status'], 'SINGLE_SOURCE')
        self.assertEqual(result['rejected_observation_count'], 1)

    def test_unknown_or_different_basis_never_manufactures_comparability(self):
        for key in observations.RESEARCH_COMPARABILITY:
            doc = document()
            doc['material_claims'][0][key] = 'UNKNOWN'
            for row in doc['source_observations']:
                row['payload'][key] = 'UNKNOWN'
            self.assertFalse(assess(doc)['all_material_claims_supported'])
        doc = document()
        doc['source_observations'][1]['payload']['basis'] = 'ADJUSTED'
        row = assess(doc)['claims'][0]
        self.assertEqual(row['status'], 'UNAVAILABLE')
        self.assertIn('NOT_COMPARABLE', row['reasons'])

    def test_hard_fact_requires_primary_authority(self):
        row = assess(document([evidence('news'), evidence('news-two')]))['claims'][0]
        self.assertEqual(row['status'], 'UNAVAILABLE')
        self.assertIn('PRIMARY_AUTHORITY_REQUIRED', row['reasons'])

    def test_latest_secondary_cannot_override_primary_or_average_conflict(self):
        second = evidence('news', value=120)
        second['published_at'] = '2026-09-13T10:00:00Z'
        row = assess(document([evidence(), second]))['claims'][0]
        self.assertEqual(row['status'], 'CONFLICTED')
        self.assertIsNone(row['value'])
        self.assertEqual(row['authority_candidate']['value'], 100)
        self.assertEqual(len(row['conflict_set']), 2)

    def test_primary_authority_is_claim_specific(self):
        row = assess(document([evidence('macro'), evidence('news')]))['claims'][0]
        self.assertEqual(row['status'], 'UNAVAILABLE')
        self.assertIn('PRIMARY_AUTHORITY_REQUIRED', row['reasons'])

    def test_missing_future_stale_times_are_not_refreshed_by_retrieval(self):
        for field, value, expected in (
            ('published_at', '', 'UNAVAILABLE'),
            ('published_at', '2028-01-01T00:00:00Z', 'UNAVAILABLE'),
            ('as_of', '2024-01-01T00:00:00Z', 'STALE'),
        ):
            rows = [evidence(), evidence('news')]
            for item in rows:
                (item['payload'] if field == 'as_of' else item)[field] = value
            result = assess(document(rows))
            self.assertEqual(result['claims'][0]['status'], expected)
            self.assertFalse(result['all_material_claims_supported'])

    def test_discovery_only_and_old_holdings_never_promote_facts(self):
        rows = [evidence(), evidence('yahoo-like')]
        self.assertEqual(assess(document(rows))['claims'][0]['status'], 'SINGLE_SOURCE')
        historical = document([evidence(kind='current_holdings'), evidence('news', kind='current_holdings')], [claim(kind='current_holdings')])
        self.assertEqual(assess(historical)['claims'][0]['status'], 'UNAVAILABLE')

    def test_source_cannot_self_declare_trust_or_publisher(self):
        raw = evidence('yahoo-like')
        raw.update(trust_tier='T1_PRIMARY_OFFICIAL', authority_class='corporate_issuer', independence_group='invented')
        result = assess(document([raw, evidence('news')]))
        self.assertFalse(result['all_material_claims_supported'])

    def test_four_source_classes_required_for_full_research(self):
        self.assertFalse(assess(document())['full_research_eligible'])
        rows = [evidence(), evidence('news'), evidence('exchange', 'price', 'market_observation'), evidence('macro', 'gdp', 'macro_indicator')]
        result = assess(document(rows))
        self.assertEqual(result['source_diversity']['source_class_count'], 4)
        self.assertTrue(result['full_research_eligible'])

    def test_secondary_concentration_generates_expansion_plan_not_network(self):
        rows = [evidence(), evidence('news')]
        for i in range(4):
            extra = evidence('news')
            extra['canonical_url'] += str(i)
            extra['content_sha256'] = format(i + 10, 'x') * 64
            rows.append(extra)
        result = assess(document(rows))
        self.assertTrue(result['source_diversity']['secondary_domain_concentrated'])
        self.assertTrue(result['source_diversity']['expansion_plan'])
        self.assertFalse(result['full_research_eligible'])

    def test_graceful_unavailable_for_legacy_missing_and_malformed_input(self):
        for doc in ({}, {'material_claims': None}, {'material_claims': [None]}, document([None])):
            result = assess(doc)
            self.assertEqual(result['status'], 'UNAVAILABLE')
            self.assertFalse(result['full_research_eligible'])

    def test_current_complete_ledger_and_expiry_are_checked_by_consumer(self):
        from datetime import timedelta
        rows = [evidence(), evidence('news'), evidence('exchange', 'price', 'market_observation'), evidence('macro', 'gdp', 'macro_indicator')]
        audit = assess(document(rows))
        self.assertTrue(observations.research_audit_high_eligible(audit, now=NOW))
        self.assertFalse(observations.research_audit_high_eligible(audit, now=NOW + timedelta(hours=3)))
        broken = copy.deepcopy(audit)
        broken['evidence'] = []
        self.assertFalse(observations.research_audit_high_eligible(broken, now=NOW))

    def test_document_cannot_self_promote_runtime_health(self):
        result = observations.reconcile_research_claims(document(), registry=REGISTRY, now=NOW)
        self.assertFalse(result['all_material_claims_supported'])

    def test_failed_health_and_missing_health_do_not_silently_become_healthy(self):
        for health in ('DEGRADED', 'CIRCUIT_OPEN', None):
            rows = [evidence(), evidence('news')]
            for item in rows:
                if health is None:
                    del item['source_health']
                else:
                    item['source_health'] = health
            self.assertFalse(assess(document(rows))['all_material_claims_supported'])

    def test_explicit_same_origin_correction_retains_old_evidence(self):
        old = evidence(value=80)
        old['published_at'] = '2026-09-11T12:00:00Z'
        old['payload']['as_of'] = old['published_at']
        old_id = observations.normalize_observation(old, registry=REGISTRY, now=NOW).observation_id
        revised = evidence()
        revised.update(correction_status='CORRECTED', supersedes_observation_id=old_id)
        result = assess(document([old, revised, evidence('news')]))
        self.assertEqual(result['claims'][0]['status'], 'SUPPORTED')
        self.assertIn(old_id, result['claims'][0]['superseded_observation_ids'])
        self.assertEqual(len(result['evidence']), 3)

    def test_actual_gateway_enrichment_consumes_claim_ledger_not_legacy_boolean(self):
        import v213_local_llm_gateway as gateway
        good = assess(document([evidence(), evidence('news'), evidence('exchange', 'price', 'market_observation'), evidence('macro', 'gdp', 'macro_indicator')]))
        for audit, expected in ((None, 'LIMITED'), (good, 'HIGH_ELIGIBLE'), (assess(document([evidence()])), 'LIMITED')):
            sidecar = {'status': 'PASS', 'records': [{'ticker': 'SYN', 'eligible_for_high_confidence_model_inference': True, 'claim_evidence_audit': audit}]}
            with patch.object(gateway, 'ORIGINAL_ENRICH', return_value=([], {'ticker': 'SYN'})), patch.object(gateway, '_load_fresh_source_audit', return_value=(sidecar, 'FRESH', 0)), patch.object(gateway, '_supplemental_federation_context', return_value='unavailable'), patch.object(observations, 'utc_now', return_value=NOW):
                enriched, context = gateway.enrich_messages([{'role': 'user', 'content': 'SYN Serenity research'}])
            self.assertEqual(context['model_confidence_cap'], expected)
            self.assertIn('SERENITY IS THE PRIMARY DECISION FRAMEWORK', enriched[0]['content'])
            self.assertIn('exact_claim_audit_status=', enriched[0]['content'])
            self.assertIn('Leopold thesis', enriched[0]['content'])

    def test_material_conflict_blocks_actual_core_and_wrapper_publication_gate(self):
        import json
        policy = json.loads(core.DEFAULT_POLICY.read_text(encoding='utf-8-sig'))
        top = [dict(document([evidence(), evidence('news', value=120)]), ticker=f'T{i:02d}', rank=i+1) for i in range(20)]
        def reconcile(record, **kwargs):
            return assess(record)
        with patch.object(core, 'reconcile_research_claims', side_effect=reconcile), patch.object(core, 'collect_observations', side_effect=lambda ticker, *args: (ticker, [])):
            result, _ = core.build(top, {}, {}, policy, {}, True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['portfolio']['material_claim_conflict_ticker_count'], 20)
        self.assertIn('MATERIAL_CLAIM_CONFLICT_REVIEW', result['violations'])
        adjusted = wrapper.apply_market_quality_policy(result, policy, wrapper._read_policy())
        self.assertEqual(adjusted['status'], 'FAIL')
        self.assertIn('MATERIAL_CLAIM_CONFLICT_REVIEW', adjusted['blocking_violations'])

    def test_core_and_wrapper_do_not_restore_legacy_pooled_high_confidence(self):
        import json
        policy = json.loads(core.DEFAULT_POLICY.read_text(encoding='utf-8-sig'))
        legacy = {'ticker': 'SYN', 'evidence': [
            dict(source_id='sec_edgar', claim_type='xbrl_fact', title='revenue', url='https://sec.gov/Archives/one', as_of=STAMP),
            dict(source_id='issuer_ir', claim_type='guidance', title='guidance', url='https://investors.counterparty.example/ir/report', as_of=STAMP)]}
        market = core.Observation('nasdaq', 'nasdaq_market', 'https://nasdaq.com/historical', 'LIVE', STAMP, as_of=STAMP, long_term_return_pct=10, short_term_return_pct=2)
        result = core.build_record(legacy, {}, {}, [market], policy, {'status': 'LIVE'})
        self.assertFalse(result['eligible_for_high_confidence_model_inference'])
        self.assertEqual(result['claim_evidence_audit']['status'], 'UNAVAILABLE')
        result['source_metrics'].update(claim_relevant_independent_families=99, claim_relevant_independent_domains=99, claim_relevant_primary_sources=99, claim_dated_evidence_ratio=1)
        result['market_corroboration']['status'] = 'CORROBORATED'
        result['missing_or_review'] = []
        self.assertFalse(wrapper._row_individually_high_eligible(result, {'comparable_count': 2, 'macro_fresh': True}, policy))


if __name__ == '__main__':
    unittest.main()

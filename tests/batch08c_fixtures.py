"""Synthetic BATCH08C caller inputs; no network, live admission or market evidence."""
import copy
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
import test_company_acquisition_bindings as binding
import test_research_v2_claims as research
import source_acquisition as acquisition
import source_observation as observation
import v213_source_independence_gate as core

NOW = binding.NOW
RUN_ID = '00000000-0000-4000-8000-000000000008'
IDENTITY_VARIANTS = dict(claim_id='other', metric='other', unit='other', period='2025Q1',
                         period_type='OBSERVED', product_or_spec='OTHER')


def binding_run(field=None, reverse=False, nonsynthetic=False, equivalent=None):
    sec, ir = (copy.deepcopy(x) for x in binding._build_test_four_factor_records('SYNB08C'))
    if field:
        ir[0]['factor_binding'][field] = IDENTITY_VARIANTS[field]
    if equivalent:
        key, mode = equivalent
        declaration = ir[0]['factor_binding']
        if mode == 'absent':
            declaration.pop(key)
        elif mode == 'padded':
            declaration[key] = '  ' + declaration[key] + '  '
        elif mode == 'lower':
            declaration[key] = declaration[key].lower()
        else:
            raise ValueError('unknown synthetic equivalence mode')
    sources = [binding.SRC_REGULATOR, binding.SRC_OFFICIAL]
    if reverse:
        sources.reverse()
        sec.reverse()
        ir.reverse()
    registry = binding.Registry(1, tuple(sources), ())
    adapters = {'sec_gov': binding.FakeBindingAdapter('sec_gov', sec),
                'official_ir': binding.FakeBindingAdapter('official_ir', ir)}
    endpoints = {name: f'https://{name}.example/report' for name in adapters}
    transport = lambda url: ('synthetic body ' + url).encode('ascii')
    with ExitStack() as stack:
        stack.enter_context(patch.dict(binding.ENDPOINTS, endpoints))
        stack.enter_context(patch.dict(binding.ADAPTERS, adapters))
        stack.enter_context(patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')))
        stack.enter_context(patch.object(acquisition, 'utc_now', return_value=NOW))
        stack.enter_context(patch.object(observation, 'utc_now', return_value=NOW))
        stack.enter_context(patch.object(acquisition.uuid, 'uuid4', return_value=RUN_ID))
        if nonsynthetic:
            # Exercise the actual non-synthetic factory branch without a network operation.
            stack.enter_context(patch.object(acquisition, 'fetch_bytes', side_effect=transport))
            return acquisition.acquire_runtime_sources(registry=registry, clock=lambda: NOW)
        return acquisition.acquire_runtime_sources(registry=registry, transport=transport, clock=NOW)


def admission_result(run, *, default=False):
    candidate, claims = binding._make_candidate_for_run('SYNB08C', run)
    options = {} if default else {'fixture_mode': False, 'acquisition_context': run}
    return binding.admission.reconcile_factor_authority(candidate, claims, 'SYNB08C', now=NOW, **options)


def research_run(mode='control', reverse=False):
    names = ('issuer', 'news', 'news-two') if mode in ('chain', 'publisher', 'three') else ('issuer', 'news')
    sources = [replace(research.REGISTRY.by_id()[name], adapter_status='implemented',
                       terms_review_status='approved', minimum_request_interval_seconds=0.0)
               for name in names]
    if mode == 'publisher':
        sources[2] = replace(sources[2], independence_group=sources[1].independence_group)
    if reverse:
        sources.reverse()
    registry = binding.Registry(1, tuple(sources), ())
    rows = {name: research.evidence(name) for name in names}
    if mode in ('origin', 'chain', 'publisher'):
        rows['news']['payload']['origin_group'] = 'issuer'
    endpoints = {name: f'https://{name}.example/report' for name in names}
    bodies = {url: ('synthetic ' + name).encode('ascii') for name, url in endpoints.items()}
    if mode == 'hash':
        bodies[endpoints['news']] = bodies[endpoints['issuer']]
    if mode == 'chain':
        bodies[endpoints['news-two']] = bodies[endpoints['news']]
    adapters = {name: binding.FakeBindingAdapter(name, [rows[name]]) for name in names}
    with patch.dict(binding.ENDPOINTS, endpoints), patch.dict(binding.ADAPTERS, adapters), \
            patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), \
            patch.object(acquisition, 'utc_now', return_value=NOW), \
            patch.object(observation, 'utc_now', return_value=NOW):
        return acquisition.acquire_runtime_sources(registry=registry, transport=bodies.__getitem__, clock=NOW)


def research_callers(run, ticker='SYN'):
    record = {'ticker': ticker, 'material_claims': [research.claim()],
              'source_observations': run.candidates_for('SYN')}
    with patch.object(core, 'now_utc', return_value=NOW), \
            patch.object(observation, 'utc_now', return_value=NOW), \
            patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
        direct = observation.reconcile_research_claims(record, acquisition_run=run, now=NOW)
        gate = core.build_record(record, {}, {}, [], {}, {}, acquisition_run=run)
    return direct, gate

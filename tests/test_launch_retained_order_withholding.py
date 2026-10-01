"""Launch: only retained order claims without a bound acquisition are withheld.

documents(False) yields fresh/baseline with unchanged membership and no SEC
fetch. When the first baseline row already carries a retained order
(positive quantities, HIGH confidence, source URLs), the reconciler must not
carry that retained order into the launch document: the row falls back to the
h6b fallback strings, UNAVAILABLE confidence, empty source URL lists and a
None retrieved_at. The baseline itself must remain untouched.
"""

import copy
import unittest

from test_reconcile_v213_order_evidence import documents, r


def test_launch_retained_order_withholding():
    fresh, baseline = documents(False)

    first = baseline['records'][0]
    first['current_orders'] = '1000000'
    first['future_orders_estimate'] = '2000000'
    first['orders_confidence'] = 'HIGH'
    first['current_order_source_urls'] = ['https://example.com/order']
    first['future_order_source_urls'] = ['https://example.com/order']
    first['retrieved_at'] = None

    # Positive bound-clock control: the second row takes the first row's
    # order fields (excluding rank and ticker) and a fixed UTC
    # retrieved_at. This is an acquisition-admission unit fixture, NOT
    # live freshness proof.
    second = baseline['records'][1]
    for field in second:
        if 'order' in field and field not in ('rank', 'ticker'):
            second[field] = copy.deepcopy(first[field])
    second['retrieved_at'] = '2026-09-13T00:00:00Z'

    baseline_copy = copy.deepcopy(baseline)

    document, receipt = r.reconcile(fresh, baseline)
    row = document['records'][0]

    assert row['current_orders'] == r.h6b.CURRENT_FALLBACK
    assert row['future_orders_estimate'] == r.h6b.FUTURE_FALLBACK
    assert row['orders_confidence'] == 'UNAVAILABLE'
    assert row['current_order_source_urls'] == []
    assert row['future_order_source_urls'] == []
    assert row['retrieved_at'] is None
    assert baseline == baseline_copy

    retained = document['records'][1]
    assert retained['current_orders'] == second['current_orders']
    assert retained['future_orders_estimate'] == second['future_orders_estimate']
    assert retained['retrieved_at'] == second['retrieved_at']
    assert retained['retrieved_at'] == '2026-09-13T00:00:00Z'
    assert receipt['withheld_retained'] == ['T00']
    assert receipt['preserved_count'] == 19


def load_tests(loader, tests, pattern):
    tests.addTest(unittest.FunctionTestCase(test_launch_retained_order_withholding))
    return tests

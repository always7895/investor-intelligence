from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sec_contact_headers as sch
import v21_serenity_top20 as v21

AT = chr(64)
CONTACT = "operator" + AT + "example.test"
MISSING_MESSAGE = (
    "SEC_CONTACT_EMAIL must be configured locally as a valid contact address"
)
OVERRIDE_MESSAGE = "SEC_USER_AGENT must include SEC_CONTACT_EMAIL"
CONTROL_MESSAGE = (
    "SEC contact or User-Agent must not contain control characters"
)
PRODUCT_MESSAGE = "product label must be a non-empty visible label"


class EnvState:
    """Fake-env context: exact presence/absence of SEC_* variables only.

    Swaps os.environ for a fixture-only plain dictionary via
    mock.patch.object for the context duration; the real environment is
    never copied, read or mutated, so NUL-bearing values never reach the
    Windows environment setter. Unset variables remain absent keys.
    """

    def __init__(self, contact=None, ua=None):
        self._fake = {}
        if contact is not None:
            self._fake["SEC_CONTACT_EMAIL"] = contact
        if ua is not None:
            self._fake["SEC_USER_AGENT"] = ua
        self._cm = None

    def __enter__(self):
        self._cm = mock.patch.object(os, "environ", self._fake)
        self._cm.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


class SecContactHeadersTests(unittest.TestCase):
    def test_default_returns_only_user_agent_and_from(self) -> None:
        with EnvState(contact=CONTACT):
            headers = sch.sec_identity_headers()
        self.assertEqual(
            headers,
            {"User-Agent": "Investor Intelligence/2.1 " + CONTACT,
             "From": CONTACT},
        )

    def test_contact_is_stripped(self) -> None:
        with EnvState(contact="  " + CONTACT + "  "):
            headers = sch.sec_identity_headers()
        self.assertEqual(headers["From"], CONTACT)
        self.assertIn(CONTACT, headers["User-Agent"])

    def test_custom_user_agent_preserved_and_stripped(self) -> None:
        with EnvState(contact=CONTACT, ua="  AuditClient/9.9 " + CONTACT + "  "):
            self.assertEqual(
                sch.sec_identity_headers()["User-Agent"],
                "AuditClient/9.9 " + CONTACT,
            )

    def test_product_label_replaces_default_prefix(self) -> None:
        with EnvState(contact=CONTACT):
            headers = sch.sec_identity_headers(product="H6B Preview/0.1")
        self.assertEqual(
            headers["User-Agent"], "H6B Preview/0.1 " + CONTACT
        )
        self.assertEqual(headers["From"], CONTACT)

    def test_product_label_stripped_and_control_rejected(self) -> None:
        with EnvState(contact=CONTACT):
            self.assertEqual(
                sch.sec_identity_headers(product="  H6B  ")["User-Agent"],
                "H6B " + CONTACT,
            )
        for bad in ("", "   ", "H6B\x1b[31m", "H6B\r\n", "\r\nH6B",
                    "H6B\n", "H6B\r"):
            with self.subTest(product=repr(bad)), EnvState(contact=CONTACT):
                with self.assertRaises(sch.SecContactError) as ctx:
                    sch.sec_identity_headers(product=bad)
            self.assertEqual(str(ctx.exception), PRODUCT_MESSAGE)
            if bad.strip():
                self.assertNotIn(bad, str(ctx.exception))

    def test_missing_contact_refused(self) -> None:
        for value in (None, ""):
            with self.subTest(contact=repr(value)), EnvState(contact=value):
                with self.assertRaises(sch.SecContactError) as ctx:
                    sch.sec_identity_headers()
            self.assertEqual(str(ctx.exception), MISSING_MESSAGE)

    def test_invalid_contact_refused_without_echo(self) -> None:
        invalid = (
            "plainaddress",
            "user" + AT + "example",
            "user" + AT + ".com",
            AT + "example.com",
            "user " + AT + "example.com",
            "two" + AT,  # missing domain entirely
        )
        for value in invalid:
            with self.subTest(contact=repr(value)), EnvState(contact=value):
                with self.assertRaises(sch.SecContactError) as ctx:
                    sch.sec_identity_headers()
            self.assertEqual(str(ctx.exception), MISSING_MESSAGE)
            self.assertNotIn(value, str(ctx.exception))

    def test_ordinary_dotted_address_accepted(self) -> None:
        ordinary = "user" + AT + "example.com"
        with EnvState(contact=ordinary):
            headers = sch.sec_identity_headers()
        self.assertEqual(headers["From"], ordinary)
        self.assertEqual(
            headers["User-Agent"], "Investor Intelligence/2.1 " + ordinary
        )

    def test_override_lacking_exact_contact_refused(self) -> None:
        for ua in ("AuditClient/9.9", "", "   ",
                   "AuditClient/9.9 operator" + AT + "example"):
            with self.subTest(ua=repr(ua)), EnvState(contact=CONTACT, ua=ua):
                with self.assertRaises(sch.SecContactError) as ctx:
                    sch.sec_identity_headers()
            self.assertEqual(str(ctx.exception), OVERRIDE_MESSAGE)
            self.assertNotIn(CONTACT, str(ctx.exception))

    def test_control_characters_rejected_without_echoing(self) -> None:
        cases = (
            ("user\x00x" + AT + "example.com", None),
            ("user\x7f" + AT + "example.com", None),
            ("user" + AT + "example.com\r", None),
            ("\n" + "user" + AT + "example.com", None),
            ("\r\n" + "user" + AT + "example.com" + "\r\n", None),
            (CONTACT, "AuditClient/9.9 " + CONTACT + "\r\nX-Injected: 1"),
            (CONTACT, "Audit\x00Client " + CONTACT),
            (CONTACT, "Audit\x7fClient " + CONTACT),
            (CONTACT, "AuditClient " + CONTACT + "\n"),
            (CONTACT, "AuditClient/9.9 " + CONTACT + "\r"),
            (CONTACT, "\nAuditClient/9.9 " + CONTACT),
            (CONTACT, "\r\nAuditClient/9.9 " + CONTACT + "\r\n"),
        )
        for contact, ua in cases:
            with self.subTest(contact=repr(contact), ua=repr(ua)):
                with EnvState(contact=contact, ua=ua):
                    with self.assertRaises(sch.SecContactError) as ctx:
                        sch.sec_identity_headers()
                message = str(ctx.exception)
                self.assertEqual(message, CONTROL_MESSAGE)
                for value in (contact, ua):
                    if value:
                        self.assertNotIn(value, message)

    def test_error_privacy_fixed_messages_only(self) -> None:
        known = {MISSING_MESSAGE, OVERRIDE_MESSAGE, CONTROL_MESSAGE}
        with EnvState(contact=None, ua=None):
            for factory in (
                lambda: sch.sec_identity_headers(),
                lambda: sch.sec_identity_headers(product=""),
            ):
                with self.assertRaises(sch.SecContactError) as ctx:
                    factory()
                self.assertIn(str(ctx.exception), known)

    def test_no_import_time_env_access(self) -> None:
        seen = []

        class SpyEnv(dict):
            def get(self, key, default=None):
                seen.append(key)
                return super().get(key, default)

            def __getitem__(self, key):
                seen.append(key)
                return super().__getitem__(key)

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "sec_contact_headers_audit_copy",
            ROOT / "scripts" / "sec_contact_headers.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.object(os, "environ", SpyEnv()):
            spec.loader.exec_module(module)
        self.assertEqual(seen, [])


class V21WrapperCompatibilityTests(unittest.TestCase):
    def test_sec_headers_returns_four_fields_with_accept_pair(self) -> None:
        with EnvState(contact=CONTACT):
            headers = v21.sec_headers()
        self.assertEqual(
            headers,
            {
                "User-Agent": "Investor Intelligence/2.1 " + CONTACT,
                "From": CONTACT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
        )

    def test_sec_headers_custom_user_agent_preserved(self) -> None:
        with EnvState(contact=CONTACT, ua="AuditClient/9.9 " + CONTACT):
            headers = v21.sec_headers()
        self.assertEqual(headers["User-Agent"], "AuditClient/9.9 " + CONTACT)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Accept-Encoding"], "gzip, deflate")

    def test_v21_uses_shared_contact_regex(self) -> None:
        self.assertIs(v21.CONTACT_RE, sch.CONTACT_RE)

    def test_missing_contact_raises_pipeline_error_with_plain_message(self) -> None:
        with EnvState(contact=None):
            with self.assertRaises(v21.PipelineError) as ctx:
                v21.sec_headers()
        self.assertEqual(str(ctx.exception), MISSING_MESSAGE)
        self.assertIsInstance(ctx.exception, RuntimeError)
        self.assertNotIn(CONTACT, str(ctx.exception))

    def test_override_without_contact_raises_pipeline_error(self) -> None:
        with EnvState(contact=CONTACT, ua="AuditClient/9.9"):
            with self.assertRaises(v21.PipelineError) as ctx:
                v21.sec_headers()
        self.assertEqual(str(ctx.exception), OVERRIDE_MESSAGE)


# ---------------------------------------------------------------------------
# Caller-level tests for the real H6B fetch_raw and federation build_live.
# Appended after the existing helper/v21 tests (which stay unchanged).
# Transport is faked only at the lowest layer (fabricated addinfourl over
# BytesIO through the ACTUAL build_opener composition, or a fake
# requests.Session.send); no real socket/DNS/process is ever created.
# ---------------------------------------------------------------------------

import email.message  # noqa: E402
import io  # noqa: E402
import tempfile  # noqa: E402
import traceback  # noqa: E402
import urllib.request  # noqa: E402
import urllib.response  # noqa: E402

import requests as requests_lib  # noqa: E402

import v213_serenity_h6b_full_top20 as h6b  # noqa: E402
import v213_source_federation as fed  # noqa: E402

SEC_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK=0001&type=10-Q"
)
NONSEC_URL = "https://towersemi.com/2026/07/14/07142026/"
NONSEC_URL2 = "https://www.sivers-semiconductors.com/press/q2-2026"
EXPECTED_SEC_UA = h6b.H6B_PRODUCT_LABEL + " " + CONTACT


class _NoTransportHTTPS(urllib.request.HTTPSHandler):
    """Sentinel transport: any https_open call proves transport contact."""

    opened = []

    def https_open(self, req):
        _NoTransportHTTPS.opened.append(req)
        return None


class _SpyEnv(dict):
    """Fake environ that records every key lookup (get/[]/in)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def get(self, key, default=None):
        self.seen.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.seen.append(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.seen.append(key)
        return super().__contains__(key)


class H6BTransportMixin:
    """Lowest-layer fake for the real per-call opener composition.

    Patches the urllib.request.HTTPSHandler CLASS with a subclass of the
    original whose https_open fabricates urllib.response.addinfourl over
    BytesIO. The real ProxyHandler, HTTPErrorProcessor and _RefuseRedirects
    handlers stay in the chain; _build_opener is NOT mocked.
    """

    @staticmethod
    def _message(pairs=()):
        msg = email.message.Message()
        for key, value in pairs:
            msg[key] = value
        return msg

    def _fake_https(self, responses):
        original = urllib.request.HTTPSHandler
        state = {"requests": [], "timeouts": [], "openers": []}

        class _FakeHTTPS(original):
            def https_open(self, req):
                state["requests"].append(req)
                state["timeouts"].append(req.timeout)
                state["openers"].append(self.parent)
                status, msg, headers, body = responses.pop(0)
                response = urllib.response.addinfourl(
                    io.BytesIO(body), headers, req.full_url, status)
                response.msg = msg
                return response

        patch = mock.patch.object(urllib.request, "HTTPSHandler", _FakeHTTPS)
        patch.__enter__()
        return patch, state


class H6BContactRefusalBeforeOpenerTests(unittest.TestCase):
    """Actual fetch_raw: invalid SEC contact state refuses BEFORE
    _build_opener (sentinel) and before any transport (sentinel class)."""

    def _refuse(self, url, contact, ua, expected):
        _NoTransportHTTPS.opened = []
        with mock.patch.object(
                h6b, "_build_opener",
                mock.MagicMock(
                    name="opener_sentinel",
                    side_effect=AssertionError(
                        "_build_opener called before header refusal"))) \
             as opener, \
             mock.patch.object(urllib.request, "HTTPSHandler",
                               _NoTransportHTTPS), \
             EnvState(contact=contact, ua=ua):
            with self.assertRaises(h6b.H6BError) as ctx:
                h6b.fetch_raw(url)
        self.assertEqual(str(ctx.exception), expected)
        self.assertEqual(opener.call_count, 0)
        self.assertEqual(_NoTransportHTTPS.opened, [])
        self.assertNotIn(CONTACT, str(ctx.exception))

    def test_a1_missing_contact_refused_before_opener(self):
        self._refuse(SEC_URL, None, None, MISSING_MESSAGE)

    def test_a2_contact_without_at_refused_before_opener(self):
        self._refuse(SEC_URL, "plainaddress", None, MISSING_MESSAGE)

    def test_a3_contact_without_tld_refused_before_opener(self):
        self._refuse(SEC_URL, "user" + AT + "example", None, MISSING_MESSAGE)

    def test_invalid_user_agent_override_refused_before_opener(self):
        self._refuse(SEC_URL, CONTACT, "BadClient/1.0", OVERRIDE_MESSAGE)


class H6BRealOpenerTransportTests(H6BTransportMixin, unittest.TestCase):
    """200/302/403 through the actual standard opener composition."""

    def _check_opener_composition(self, opener, req):
        for banned in (urllib.request.HTTPBasicAuthHandler,
                       urllib.request.HTTPDigestAuthHandler,
                       urllib.request.ProxyBasicAuthHandler,
                       urllib.request.ProxyDigestAuthHandler,
                       urllib.request.HTTPCookieProcessor):
            self.assertFalse(
                any(isinstance(h, banned) for h in opener.handlers),
                banned.__name__)
        self.assertIsNone(req.get_header("Accept-encoding"))

    def test_200_sec_identity_headers_real_opener(self):
        pre_global = urllib.request._opener
        patch, state = self._fake_https([(200, "OK",
                                          self._message(
                                              [("Content-Type",
                                                "text/plain; charset=utf-8")]),
                                          "ok body".encode("utf-8"))])
        real_build = urllib.request.build_opener
        proxies_env = mock.MagicMock(
            name="getproxies_sentinel",
            side_effect=AssertionError("ambient proxy env lookup"))
        try:
            with mock.patch.object(
                    urllib.request, "build_opener",
                    wraps=real_build) as build_spy, \
                 mock.patch.object(urllib.request, "getproxies",
                                   proxies_env):
                with EnvState(contact=CONTACT):
                    text = h6b.fetch_raw(SEC_URL, timeout=7.5)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(text, "ok body")
        self.assertEqual(len(state["requests"]), 1)
        req = state["requests"][0]
        self.assertEqual(req.get_header("User-agent"), EXPECTED_SEC_UA)
        self.assertEqual(req.get_header("From"), CONTACT)
        self.assertEqual(state["timeouts"], [7.5])
        self.assertEqual(build_spy.call_count, 1)
        explicit_proxy = build_spy.call_args.args[0]
        self.assertIsInstance(explicit_proxy, urllib.request.ProxyHandler)
        self.assertEqual(explicit_proxy.proxies, {})
        self.assertEqual(proxies_env.call_count, 0)
        self._check_opener_composition(state["openers"][0], req)
        self.assertIs(urllib.request._opener, pre_global)

    def test_200_custom_user_agent_preserved(self):
        patch, state = self._fake_https([(200, "OK",
                                          self._message(
                                              [("Content-Type",
                                                "text/plain")]),
                                          b"ok")])
        try:
            with EnvState(contact=CONTACT, ua="AuditClient/9.9 " + CONTACT):
                h6b.fetch_raw(SEC_URL)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(len(state["requests"]), 1)
        req = state["requests"][0]
        self.assertEqual(
            req.get_header("User-agent"), "AuditClient/9.9 " + CONTACT)
        self.assertEqual(req.get_header("From"), CONTACT)
        self.assertEqual(state["timeouts"], [20.0])

    def test_200_charset_from_content_type(self):
        patch, state = self._fake_https([(200, "OK",
                                          self._message(
                                              [("Content-Type",
                                                "text/plain; "
                                                "charset=iso-8859-1")]),
                                          "caf\u00e9".encode("iso-8859-1"))])
        try:
            with EnvState(contact=CONTACT):
                text = h6b.fetch_raw(SEC_URL)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(text, "caf\u00e9")

    def test_oversize_body_refused_after_single_read(self):
        patch, state = self._fake_https([(200, "OK",
                                          self._message(
                                              [("Content-Type",
                                                "text/plain")]),
                                          b"x" * (24 * 1024 * 1024 + 100))])
        try:
            with EnvState(contact=CONTACT):
                with self.assertRaises(h6b.H6BError) as ctx:
                    h6b.fetch_raw(SEC_URL)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(
            str(ctx.exception), "response too large: " + SEC_URL)
        self.assertEqual(len(state["requests"]), 1)

    def test_302_refused_by_real_redirect_handler_single_request(self):
        patch, state = self._fake_https([(302, "Found",
                                          self._message(
                                              [("Location",
                                                "https://www.sec.gov/"
                                                "redirected")]),
                                          b"")])
        try:
            with EnvState(contact=CONTACT):
                with self.assertRaises(h6b.H6BError) as ctx:
                    h6b.fetch_raw(SEC_URL)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(str(ctx.exception), h6b.REFUSED_REDIRECT)
        self.assertEqual(len(state["requests"]), 1)
        self.assertNotIn("redirected", str(ctx.exception))

    def test_403_sanitized_no_reason_canary_leak(self):
        canary = "CANARY-403-REASON-9F3A"
        patch, state = self._fake_https([(403, "FORBIDDEN-" + canary,
                                          self._message(
                                              [("Server", canary),
                                               ("Content-Type",
                                                "text/plain")]),
                                          b"forbidden")])
        try:
            with EnvState(contact=CONTACT):
                with self.assertRaises(h6b.H6BError) as ctx:
                    h6b.fetch_raw(SEC_URL)
        finally:
            patch.__exit__(None, None, None)
        self.assertEqual(len(state["requests"]), 1)
        self.assertEqual(
            str(ctx.exception), "fetch failed: " + SEC_URL + ": HTTPError")
        self.assertIsNone(ctx.exception.__cause__)
        formatted = "".join(traceback.format_exception(ctx.exception))
        self.assertNotIn(canary, str(ctx.exception))
        self.assertNotIn(canary, formatted)


class H6BHostScopeTests(H6BTransportMixin, unittest.TestCase):
    """URL-scoped identity: exact SEC hosts only; every other host is
    generic and never calls the shared helper or reads SEC env vars."""

    def test_normalized_aliases_carry_identity(self):
        for url in ("https://SEC.GOV/x", "https://WWW.SEC.GOV./x",
                    "https://data.sec.gov/x"):
            with self.subTest(url=url):
                patch, state = self._fake_https([(200, "OK",
                                                  self._message(
                                                      [("Content-Type",
                                                        "text/plain")]),
                                                  b"ok")])
                try:
                    with EnvState(contact=CONTACT):
                        h6b.fetch_raw(url)
                finally:
                    patch.__exit__(None, None, None)
                self.assertEqual(len(state["requests"]), 1)
                req = state["requests"][0]
                self.assertEqual(req.get_header("From"), CONTACT)
                self.assertEqual(req.get_header("User-agent"),
                                 EXPECTED_SEC_UA)

    def test_nonsec_never_calls_helper_or_reads_sec_env(self):
        for url in (NONSEC_URL, NONSEC_URL2):
            with self.subTest(url=url):
                fake_env = _SpyEnv()
                fake_env["SEC_CONTACT_EMAIL"] = CONTACT
                fake_env["SEC_USER_AGENT"] = "Poisoned/1.0 " + CONTACT
                helper_calls = []
                patch, state = self._fake_https([(200, "OK",
                                                  self._message(
                                                      [("Content-Type",
                                                        "text/plain")]),
                                                  b"nonsec")])
                try:
                    with mock.patch.object(os, "environ", fake_env), \
                         mock.patch.object(
                             h6b, "sec_identity_headers",
                             side_effect=lambda **kw: helper_calls.append(
                                 kw)):
                        text = h6b.fetch_raw(url)
                finally:
                    patch.__exit__(None, None, None)
                self.assertEqual(text, "nonsec")
                self.assertEqual(helper_calls, [])
                self.assertEqual(
                    [k for k in fake_env.seen if k.startswith("SEC_")], [])
                req = state["requests"][0]
                self.assertEqual(
                    req.get_header("User-agent"), h6b.H6B_PRODUCT_LABEL)
                self.assertIsNone(req.get_header("From"))
                joined = " ".join(v for _, v in req.header_items())
                self.assertNotIn(CONTACT, joined)

    def test_spoof_suffix_hosts_generic_and_isolated(self):
        for url in ("https://sec.gov.evil.test/x", "https://notsec.gov/x"):
            with self.subTest(url=url):
                fake_env = _SpyEnv()
                fake_env["SEC_CONTACT_EMAIL"] = CONTACT
                fake_env["SEC_USER_AGENT"] = "Poisoned/1.0 " + CONTACT
                helper_calls = []
                patch, state = self._fake_https([(200, "OK",
                                                  self._message(
                                                      [("Content-Type",
                                                        "text/plain")]),
                                                  b"ok")])
                try:
                    with mock.patch.object(os, "environ", fake_env), \
                         mock.patch.object(
                             h6b, "sec_identity_headers",
                             side_effect=lambda **kw: helper_calls.append(
                                 kw)):
                        h6b.fetch_raw(url)
                finally:
                    patch.__exit__(None, None, None)
                self.assertEqual(helper_calls, [])
                self.assertEqual(
                    [k for k in fake_env.seen if k.startswith("SEC_")], [])
                req = state["requests"][0]
                self.assertIsNone(req.get_header("From"))
                self.assertEqual(
                    req.get_header("User-agent"), h6b.H6B_PRODUCT_LABEL)


class H6BAuthorityRefusalBeforeOpenerTests(unittest.TestCase):
    """Scheme/authority refusals happen BEFORE any opener or transport."""

    def _refuse(self, url, expected):
        _NoTransportHTTPS.opened = []
        with mock.patch.object(
                h6b, "_build_opener",
                mock.MagicMock(
                    name="opener_sentinel",
                    side_effect=AssertionError(
                        "_build_opener called before refusal"))) \
             as opener, \
             mock.patch.object(urllib.request, "HTTPSHandler",
                               _NoTransportHTTPS):
            with self.assertRaises(h6b.H6BError) as ctx:
                h6b.fetch_raw(url)
        self.assertEqual(str(ctx.exception), expected)
        self.assertEqual(opener.call_count, 0)
        self.assertEqual(_NoTransportHTTPS.opened, [])

    def test_userinfo_refused_before_opener(self):
        self._refuse("https://user:pass@www.sec.gov/x", h6b.REFUSED_USERINFO)

    def test_http_scheme_refused_before_opener(self):
        self._refuse("http://www.sec.gov/x", h6b.REFUSED_SCHEME)

    def test_non_default_port_refused_before_opener(self):
        self._refuse("https://www.sec.gov:8443/x", h6b.REFUSED_PORT)

    def test_invalid_port_refused_before_opener(self):
        self._refuse("https://www.sec.gov:99999/x", h6b.REFUSED_PORT)

    def test_percent_encoded_authority_refused_before_opener(self):
        self._refuse("https://www.sec.gov%2fevil.test/x",
                     h6b.REFUSED_AUTHORITY)

    def test_backslash_authority_refused_before_opener(self):
        self._refuse("https://www\\.sec\\.gov/x", h6b.REFUSED_AUTHORITY)

    def test_missing_authority_refused_before_opener(self):
        self._refuse("https:///x", h6b.REFUSED_AUTHORITY)


class _StopCollectors(BaseException):
    """Fake-transport stop token; not an Exception, so build_live's
    per-source except-Exception fallbacks cannot swallow it."""


class FederationBuildLiveCallerTests(unittest.TestCase):
    def test_build_live_first_send_generic_identity_no_contact(self):
        sent = []

        def fake_send(self_session, request, **kwargs):
            sent.append((self_session, request))
            raise _StopCollectors("stop after first send")

        cache_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cache_dir.cleanup)
        top20 = [{"ticker": "T%02d" % index, "rank": index,
                  "name": "Company %d" % index}
                 for index in range(1, 21)]
        with mock.patch.object(requests_lib.Session, "send", fake_send), \
             mock.patch.object(fed, "CACHE_ROOT", Path(cache_dir.name)), \
             EnvState(contact=CONTACT, ua="Poisoned/1.0 " + CONTACT):
            with self.assertRaises(_StopCollectors):
                fed.build_live(top20, {}, {})
        self.assertEqual(len(sent), 1)
        session, prep = sent[0]
        self.assertIs(session.trust_env, False)
        self.assertEqual(prep.method, "GET")
        self.assertEqual(prep.url, fed.NASDAQ_LISTED_URL)
        self.assertEqual(
            prep.headers["User-Agent"], fed.FEDERATION_USER_AGENT)
        self.assertNotIn("From", prep.headers)
        joined = " ".join("%s: %s" % (key, value)
                          for key, value in prep.headers.items())
        self.assertNotIn(CONTACT, joined)
        self.assertNotIn("Poisoned", joined)


# ---------------------------------------------------------------------
# F1: transport-unserializable identity values and transport UnicodeError.
#
# The serialize fixture below runs ACTUAL fetch_raw with the real per-call
# opener composition; only the HTTPSHandler class is replaced. Its
# https_open builds a local http.client.HTTPConnection('fixture.invalid'),
# issues putrequest('GET', '/', skip_host=True,
# skip_accept_encoding=True), then putheader() for every captured request
# header. putrequest/putheader only append to the connection's in-memory
# buffer; endheaders/send/request/connect are NEVER called, so no socket
# audit event can fire. This exercises real CPython ASCII header
# serialization offline: a non-Latin-1 header value raises the real
# UnicodeEncodeError inside putheader (the F1 surface).
# ---------------------------------------------------------------------

import http.client  # noqa: E402

UNADMITTED_MESSAGE = "SEC_IDENTITY_HEADERS_UNADMITTED"


class _SerializedStop(BaseException):
    """Stop token carrying the locally serialized header buffer bytes."""

    def __init__(self, payload):
        super().__init__("local header serialization complete")
        self.payload = payload


class _SerializeHeadersHTTPS(urllib.request.HTTPSHandler):
    """Real CPython header serialization WITHOUT sockets (see above)."""

    opened = []

    def https_open(self, req):
        _SerializeHeadersHTTPS.opened.append(req)
        conn = http.client.HTTPConnection("fixture.invalid")
        conn.putrequest("GET", "/", skip_host=True,
                        skip_accept_encoding=True)
        for key, value in req.header_items():
            conn.putheader(key, value)
        raise _SerializedStop(b"".join(conn._buffer))


class _RaiseUnicodeErrorHTTPS(urllib.request.HTTPSHandler):
    """Transport that fails exactly like http.client serialization: raises
    the real UnicodeEncodeError, retaining the sensitive offending value on
    the exception object (the F1 leak surface)."""

    opened = []
    error = None

    def https_open(self, req):
        _RaiseUnicodeErrorHTTPS.opened.append(req)
        _RaiseUnicodeErrorHTTPS.error = UnicodeEncodeError(
            "ascii", "CANARY-TRANSPORT-7C2E \u2603 " + CONTACT,
            0, 1, "invalid start byte")
        raise _RaiseUnicodeErrorHTTPS.error


class H6BHeaderEncodingTests(unittest.TestCase):
    """F1: transport-unserializable identity values must be refused BEFORE
    the opener via the fixed non-echoing helper error; a transport
    UnicodeError must be sanitized to the fixed H6BError message. The
    serialize fixture exercises real CPython putrequest/putheader on local
    buffers (no sockets); the real _build_opener composition is kept and
    only counted via wraps."""

    def _refuse_serialization(self, contact, ua, expected):
        _SerializeHeadersHTTPS.opened = []
        real_build = h6b._build_opener
        with mock.patch.object(
                h6b, "_build_opener",
                mock.MagicMock(
                    wraps=real_build, name="opener_count")) as opener, \
             mock.patch.object(urllib.request, "HTTPSHandler",
                               _SerializeHeadersHTTPS), \
             EnvState(contact=contact, ua=ua):
            with self.assertRaises(h6b.H6BError) as ctx:
                h6b.fetch_raw(SEC_URL)
        self.assertEqual(str(ctx.exception), expected)
        self.assertEqual(opener.call_count, 0)
        self.assertEqual(_SerializeHeadersHTTPS.opened, [])
        return str(ctx.exception)

    def _serialize(self, contact, ua):
        _SerializeHeadersHTTPS.opened = []
        real_build = h6b._build_opener
        with mock.patch.object(
                h6b, "_build_opener",
                mock.MagicMock(
                    wraps=real_build, name="opener_count")) as opener, \
             mock.patch.object(urllib.request, "HTTPSHandler",
                               _SerializeHeadersHTTPS), \
             EnvState(contact=contact, ua=ua):
            with self.assertRaises(_SerializedStop) as ctx:
                h6b.fetch_raw(SEC_URL)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(len(_SerializeHeadersHTTPS.opened), 1)
        return ctx.exception.payload

    def test_unicode_override_refused_before_opener(self):
        message = self._refuse_serialization(
            CONTACT, "\u2603 " + CONTACT, UNADMITTED_MESSAGE)
        self.assertNotIn("\u2603", message)
        self.assertNotIn(CONTACT, message)

    def test_unicode_contact_default_ua_refused_before_opener(self):
        # '\u2603operator@example.test' still fullmatches CONTACT_RE
        # (neither '@' nor whitespace), which is exactly the F1 hole.
        message = self._refuse_serialization(
            "\u2603" + CONTACT, None, UNADMITTED_MESSAGE)
        self.assertNotIn("\u2603", message)

    def test_unicode_product_label_refused(self):
        with EnvState(contact=CONTACT, ua=None):
            with self.assertRaises(sch.SecContactError) as ctx:
                sch.sec_identity_headers(product="H6B \u2603")
        self.assertEqual(str(ctx.exception), UNADMITTED_MESSAGE)
        self.assertNotIn("\u2603", str(ctx.exception))

    def test_ascii_control_contact_still_refused_before_opener(self):
        # Raw-control-first rule unchanged: ASCII control is refused with
        # the existing fixed message before the opener.
        self._refuse_serialization(CONTACT + "\x00", None, CONTROL_MESSAGE)

    def test_ascii512_override_admitted_and_serialized(self):
        prefix = "A" * (512 - len(CONTACT) - 1)
        ua = prefix + " " + CONTACT
        self.assertEqual(len(ua), 512)
        buffer = self._serialize(CONTACT, ua)
        raw = buffer.decode("ascii")
        self.assertTrue(raw.startswith("GET / HTTP/1."))
        text = raw.casefold()
        self.assertIn("user-agent: " + ua.casefold(), text)
        self.assertIn("from: " + CONTACT.casefold(), text)

    def test_ascii513_override_refused_before_opener(self):
        prefix = "A" * (513 - len(CONTACT) - 1)
        ua = prefix + " " + CONTACT
        self.assertEqual(len(ua), 513)
        self._refuse_serialization(CONTACT, ua, UNADMITTED_MESSAGE)

    def test_unicode_encode_error_transport_sanitized(self):
        # Valid ASCII identity; the transport itself fails with a real
        # UnicodeEncodeError that retains the sensitive value. fetch_raw
        # must sanitize: fixed H6BError, no chain, canary absent from the
        # str and formatted exception.
        _RaiseUnicodeErrorHTTPS.opened = []
        _RaiseUnicodeErrorHTTPS.error = None
        with mock.patch.object(urllib.request, "HTTPSHandler",
                               _RaiseUnicodeErrorHTTPS), \
             EnvState(contact=CONTACT, ua=None):
            with self.assertRaises(h6b.H6BError) as ctx:
                h6b.fetch_raw(SEC_URL)
        self.assertEqual(len(_RaiseUnicodeErrorHTTPS.opened), 1)
        canary = _RaiseUnicodeErrorHTTPS.error.object
        self.assertIsInstance(canary, str)
        self.assertIn("\u2603", canary)
        self.assertEqual(
            str(ctx.exception),
            "fetch failed: " + SEC_URL + ": UnicodeEncodeError")
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)
        rendered = "".join(traceback.format_exception(ctx.exception))
        self.assertNotIn(canary, str(ctx.exception))
        self.assertNotIn(canary, rendered)
        self.assertNotIn(CONTACT, rendered)
        self.assertNotIn("\u2603", rendered)


if __name__ == "__main__":
    unittest.main()

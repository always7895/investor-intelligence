"""F02D protected same-owner host. SOURCE ONLY / IMPLEMENTED_UNVERIFIED.

Only bootstrap's protected -I -S -B entry may dispatch serve(). Std handles are
invocation-local inherited pipes, never TCP/public named endpoints. Wire intents
are NOT authority. Real lease/version/snapshot/consumption/witness stay here.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import revenue_guidance_provisioner as provisioner
import revenue_guidance_windows as windows
import revenue_guidance_overlay as overlay
import revenue_guidance_revision as revision

PROTOCOL = "guidance-private-host-v1"
MAX_FRAME = 16384
MAX_REQUESTS = 64
GIR = re.compile(r"gir1:[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,23}\Z")
OPS = frozenset(("Open", "ReadJournal", "ReadInputRevision", "CommitJournal", "CheckRelease", "Update",
                 "RankAndComplete", "ReadRebuildCompletion", "ExportPublicBundle", "Close"))
PUBLIC_FILES = {
    "identity": "identity_shards_latest.json", "names": "zh_names_latest.json",
    "deep": "company_deep_reports_latest.json", "prices": "price_shards_latest.json",
    "consensus": "revenue_consensus_quarterly.json", "serenity": "serenity_signals_latest.json",
    "leopold": "leopold_positions_latest.json", "tickers": "v21/company_tickers_exchange.json",
    "cision": "cision_interim_revenue.json",
}
CONFIG_FILES = {
    "layers": "bottleneck-layers-v3.json", "lineage": "listing-lineage-v1.json",
    "official_names": "company-zh-names-v1.json", "official_quarters": "official-quarterly-revenue-v1.json",
    "claims": "order-claims-v2.json", "korea_orders": "korea-ir-orders-v1.json",
    "korea_fundamentals": "korea-ir-fundamentals-v1.json",
}


class HostUnavailable(RuntimeError):
    def __init__(self, reason="HOST_UNAVAILABLE"):
        super().__init__(reason)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw, cap=MAX_FRAME, *, max_nodes=65536):
    if type(raw) is not bytes or not raw or len(raw) > cap:
        raise HostUnavailable("JSON_BOUND")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise HostUnavailable("JSON_DUPLICATE")
            result[key] = value
        return result
    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(HostUnavailable("JSON_NONFINITE")))
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if depth > 32 or count > max_nodes or (type(item) is float and not math.isfinite(item)):
            raise HostUnavailable("JSON_BOUND")
        if type(item) is dict:
            if len(item) > 8192:
                raise HostUnavailable("JSON_BOUND")
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > 131072:
                raise HostUnavailable("JSON_BOUND")
            stack.extend((child, depth + 1) for child in item)
    return value


class _SafeDiagnostic(io.TextIOBase):
    """Library output never enters protocol or raw stderr/traceback artifacts."""
    def __init__(self, sink):
        self.sink, self.observed = sink, False
    def write(self, text):
        if text and not self.observed:
            self.observed = True
            self.sink.write("HOST_LIBRARY_DIAGNOSTIC\n")
            self.sink.flush()
        return len(text)
    def flush(self):
        self.sink.flush()


class _PinnedTLS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address
    def connect(self):
        plain = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(plain, server_hostname=self.host)
        except BaseException:
            plain.close()  # failed TLS wrapping must not lose the actual TCP owner
            raise


class _AcquisitionDeferred(BaseException):
    """Known staged progress, NOT swallowed by legacy optional-channel handlers."""


class _CaptureControlFault(BaseException):
    """Budget/authority/storage/deadline faults are not optional market absence."""


class _Capture:
    """Actual captured public observations + approved config/code bytes.

    Not a verifier callback/authority/path facade. Fixed sources only; network
    budget shared with the same check/updater lease. No proxy/cookies or disk cache.
    """
    def __init__(self, owner):
        self.owner = owner
        self.entries, self.observations = {}, {}
        self.origin = provisioner.controlled_origin()
        self.release_id = self.origin.policy["release_id"]
        self.code = {name: digest(raw) for name, raw in self.origin.files.items() if name.startswith("scripts/")}
        self.closed = False
        self.outputs = None
        self.plan_keys, self.plan_specs, self.batch = {}, {}, []
        self.network_allowed = False
        self.progress_state = None

    def close(self):
        if not self.closed:
            self.closed = True
            self.origin.close()  # existing r2 actual-origin failure/lifetime seam

    def file(self, name, relative, cap=8 * 1024 * 1024):
        self.owner.remaining()
        raw, observed = self.origin.capture_public_input(relative, self.owner.lease.budget, cap)
        if raw is not None:
            strict_json(raw, cap, max_nodes=1000000)
        self.entries[name], self.observations[name] = raw, observed
        return raw

    def fetch(self, url, *, issuer="ranking", optional=False, cap=8 * 1024 * 1024):
        key = "http/" + url
        if key in self.entries:
            raw = self.entries[key]
            if raw is None and not optional:
                raise HostUnavailable("PUBLIC_SOURCE_UNAVAILABLE")
            return raw
        parsed = urlsplit(url)
        allowed = {
            "data.sec.gov": ("/api/xbrl/companyfacts/",), "efts.sec.gov": ("/LATEST/search-index",),
            "query1.finance.yahoo.com": ("/v8/finance/chart/", "/v10/finance/quoteSummary/", "/ws/fundamentals-timeseries/"),
            "api.nasdaq.com": ("/api/analyst/",), "openapi.twse.com.tw": ("/v1/opendata/t187ap05_L",),
            "www.tpex.org.tw": ("/openapi/v1/mopsfin_t187ap05_O",), "news.cision.com": ("/",),
        }
        host = parsed.hostname
        if (host not in allowed or parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443) or len(url) > 4096 or not parsed.path.startswith(allowed[host])):
            raise HostUnavailable("PUBLIC_URL_REFUSED")
        if self.outputs is not None:
            slot = self.plan_keys.get(url, digest(url.encode()))
            cached = self.outputs.captured_public(slot, url, now(), 20 if host == "data.sec.gov" else 3)
            if cached is not None:
                raw, record = cached
                self.entries[key] = raw
                # Explicitly caller-writable public cache, NOT TLS revalidation,
                # code authority or fresh financial evidence. Never mint witness
                # from this metadata; only actual model consumption qualifies.
                self.observations[key] = {"status": "HELD_PUBLIC_CACHE_UNAUTHENTICATED",
                    "claimed_retrieved_at": record["retrieved_at"], "source_status": record["status"],
                    "http_status": record["http_status"], "sha256": digest(raw) if raw is not None else None}
                if raw is None and not optional:
                    raise HostUnavailable("PUBLIC_SOURCE_UNAVAILABLE")
                return raw
        if not self.network_allowed:
            # Dynamic real-builder sources (FX/Cision/new URL) are persisted in a
            # subsequent fair batch, never disguised as missing completed input.
            raise _AcquisitionDeferred()
        work = getattr(self.owner.lease, "_network_work", None)
        if work is None:
            work = {"requests": 0, "bytes": 0, "last": None, "issuers": {}}
            self.owner.lease._network_work = work
        elapsed = self.owner.remaining()
        if work["requests"] >= 120 or work["issuers"].get(issuer, 0) >= 24:
            raise _AcquisitionDeferred()
        if work["last"] is not None:
            delay = max(0.0, 0.5 - (time.monotonic() - work["last"]))
            if delay >= elapsed:
                raise HostUnavailable("REQUEST_DEADLINE")
            time.sleep(delay)
        work["requests"] += 1
        work["issuers"][issuer] = work["issuers"].get(issuer, 0) + 1
        work["last"] = time.monotonic()
        connection = response = None
        headers = (dict(self.owner.sec_headers) if host in ("data.sec.gov", "efts.sec.gov") else
                   {"User-Agent": "Mozilla/5.0 (InvestorIntelligence public observation)"})
        headers["Accept-Encoding"] = "identity"
        raw, status = None, None
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            self.owner.remaining()  # DNS timeout is not cancellation/deadline reset
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise HostUnavailable("PUBLIC_DNS_REFUSED")
            connection = _PinnedTLS(host, addresses[0][4][0], min(30.0, self.owner.remaining()))
            connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers=headers)
            response = connection.getresponse()
            status = response.status
            # getresponse() may detach connection.sock on valid will_close/EOF
            # responses. The actual response-owned SocketIO retains its socket.
            readable_socket = response.fp.raw._sock if response.fp is not None else None
            if response.getheader("Content-Encoding", "identity").lower() not in ("identity", ""):
                raise HostUnavailable("PUBLIC_ENCODING_REFUSED")
            chunks, size = [], 0
            while True:
                left = self.owner.remaining()
                if readable_socket is not None:
                    readable_socket.settimeout(min(30.0, left))
                chunk = response.read(min(65536, cap + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                work["bytes"] += len(chunk)
                if size > cap or work["bytes"] > 128 * 1024 * 1024:
                    raise HostUnavailable("NETWORK_CAPACITY_UNAVAILABLE")
                chunks.append(chunk)
                if response.isclosed():
                    break  # final known-length/chunked read may close the last socket IO owner
            if response.length is not None and response.length != 0:
                raise http.client.IncompleteRead(b"", response.length)  # typed transport absence, not a valid truncated body
            captured = b"".join(chunks)
            if status == 200:
                raw = captured
                self.owner.lease.budget.admit_capture(len(raw), raw_document=cap > 8 * 1024 * 1024)
                # Persisted as packed actual bytes with the original observation
                # time at batch readback, NOT one directory leaf per URL.
            elif not optional:
                raise HostUnavailable("PUBLIC_SOURCE_UNAVAILABLE")
            # Failed public source remains a distinct observed HTTP failure, not
            # evidence of an empty/nondisclosed successful source.
            observed_at = now()
            self.entries[key] = raw
            self.observations[key] = {"status": "CAPTURED" if status == 200 else "HTTP_UNAVAILABLE",
                                      "http_status": status, "observed_at": observed_at.isoformat(),
                                      "sha256": digest(raw) if raw is not None else None}
            self.owner.remaining()
            self.batch.append((self.plan_keys.get(url, digest(url.encode())), url, raw, observed_at,
                               "CAPTURED" if status == 200 else "HTTP_UNAVAILABLE", status))
            return raw
        except (OSError, http.client.HTTPException):
            self.owner.remaining()  # deadline/budget/custody faults still propagate
            if not optional:
                raise HostUnavailable("PUBLIC_TRANSPORT_UNAVAILABLE") from None
            observed_at = now()
            self.entries[key] = None
            self.observations[key] = {"status": "TRANSPORT_UNAVAILABLE", "observed_at": observed_at.isoformat(),
                                      "sha256": None}
            self.batch.append((self.plan_keys.get(url, digest(url.encode())), url, None, observed_at, "TRANSPORT_UNAVAILABLE", None))
            return None  # typed absence, never fabricated successful empty source
        finally:
            try:
                if response is not None:
                    response.close()  # response-owned readable stream, including will_close
            finally:
                if connection is not None:
                    connection.close()  # never native NT cancellation/owner close workaround

    def collect(self, outputs):
        import bottleneck_top20_v3 as ranking
        self.outputs = outputs
        for name, relative in CONFIG_FILES.items():
            raw = self.origin.files["config/" + relative]
            strict_json(raw, 8 * 1024 * 1024, max_nodes=1000000)
            self.entries[name] = raw
            self.observations[name] = {"status": "PROTECTED_CAPTURE", "sha256": digest(raw)}
        for name, relative in PUBLIC_FILES.items():
            self.file(name, relative)
        cision = outputs.load_cision()
        if cision is not None:
            strict_json(cision, 1024 * 1024)
            self.entries["cision"] = cision
            self.observations["cision"] = {"status": "HELD_CAPTURE", "sha256": digest(cision)}
        layers = strict_json(self.entries["layers"], 8 * 1024 * 1024)["layers"]
        members = sorted({entry["symbol"] for layer in layers for entry in layer["capturers"]})
        if not members or len(members) > 256 or any(not SYMBOL.fullmatch(s) for s in members):
            raise HostUnavailable("RANKING_SCOPE_UNAVAILABLE")
        tickers = strict_json(self.entries["tickers"], 8 * 1024 * 1024)
        ciks = {str(dict(zip(tickers["fields"], row))["ticker"]).upper(): int(dict(zip(tickers["fields"], row))["cik"])
                for row in tickers["data"]}
        reference_day = now()
        start = int(datetime.combine(reference_day.date() - timedelta(days=366 * 3), datetime.min.time(), timezone.utc).timestamp())
        end = int(datetime.combine(reference_day.date() + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp())
        # Finite logical slots are stable across date-specific URL windows.
        # The actual 60-member universe is NOT shrunk to fit one request cycle.
        plan = []
        def add(role, url, issuer="ranking", cap=8 * 1024 * 1024):
            slot = digest(role.encode())
            if url not in self.plan_specs:
                self.plan_keys[url], self.plan_specs[url] = slot, (issuer, cap)
                plan.append((slot, url, issuer, cap))
        for symbol in members:
            self.owner.remaining()
            encoded_symbol = quote(symbol, safe="")
            add("yahoo/chart/" + symbol, f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?period1={start}&period2={end}&interval=1d&events=div%2Csplits", symbol)
            add("yahoo/summary/" + symbol, f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{encoded_symbol}?modules=price%2CfinancialData%2CearningsTrend", symbol)
            add("yahoo/financials/" + symbol, f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{encoded_symbol}?type=quarterlyTotalRevenue%2CquarterlyGrossProfit%2CquarterlyDilutedAverageShares&period1={start}&period2={end}", symbol)
            if "." not in symbol:
                for suffix in ("targetprice", "earnings-forecast"):
                    # Same real Nasdaq parser's URLs, captured before scoring.
                    add("nasdaq/" + symbol + "/" + suffix,
                        ranking.NASDAQ_ANALYST.format(symbol=quote(symbol.replace("-", ".").lower()), kind=suffix), symbol)
            cik = ciks.get(symbol) if "." not in symbol else None
            if cik:
                raw = self.file(f"facts/CIK{cik:010d}", f"v3/companyfacts/CIK{cik:010d}.json", 16 * 1024 * 1024)
                metadata = self.observations[f"facts/CIK{cik:010d}"]
                written = metadata.get("last_write_filetime", 0) / 10000000 - 11644473600
                if raw is None or not 0 <= time.time() - written < 20 * 3600:
                    raw = None
                    add(f"facts/CIK{cik:010d}", ranking.COMPANYFACTS.format(cik=cik), symbol, 16 * 1024 * 1024)
                self.entries[f"facts/CIK{cik:010d}"] = raw
        for suffix, value in ranking.TAIWAN_MONTHLY_REVENUE.items():
            add("taiwan/" + suffix, value[1], "taiwan")
        for layer in layers:
            for term in layer["filing_terms"]:
                for label, days1, days2 in (("recent", 30, 0), ("prior", 90, 31)):
                    url = ranking.EFTS.format(query=quote(f'"{term}"'),
                        start=(reference_day.date() - timedelta(days=days1)).isoformat(),
                        end=(reference_day.date() - timedelta(days=days2)).isoformat())
                    add("news/" + term + "/" + label, url, "news/" + term)
        # Actual charts determine FX and actual RSS determines report pages.
        # These extensions use their own stable slots/cursor in the same index.
        self._acquire(plan, outputs, "base")
        currencies = set()
        for symbol in members:
            for kind in ("chart", "summary", "financials"):
                role = "yahoo/" + kind + "/" + symbol
                url = next(url for slot, url, _, _ in plan if slot == digest(role.encode()))
                self.entries[role] = self.fetch(url, issuer=symbol, optional=True)
                self.observations[role] = dict(self.observations["http/" + url])
            summary_currency = None
            summary = self.entries["yahoo/summary/" + symbol]
            if summary:
                try:
                    summary_currency = strict_json(summary, 8 * 1024 * 1024)["quoteSummary"]["result"][0].get("price", {}).get("currency")
                except (ValueError, KeyError, TypeError, IndexError):
                    pass
            chart = self.entries["yahoo/chart/" + symbol]
            if chart:
                try:
                    currency = strict_json(chart, 8 * 1024 * 1024)["chart"]["result"][0].get("meta", {}).get("currency")
                except (ValueError, KeyError, TypeError, IndexError):
                    currency = None
                currency = summary_currency or currency  # exactly the real adapter's precedence
                if currency and currency != "USD":
                    if type(currency) is not str or not re.fullmatch(r"[A-Za-z]{3}", currency):
                        raise HostUnavailable("CURRENCY_UNAVAILABLE")
                    currencies.add(currency)
            cik = ciks.get(symbol) if "." not in symbol else None
            if cik and self.entries[f"facts/CIK{cik:010d}"] is None:
                url = ranking.COMPANYFACTS.format(cik=cik)
                self.entries[f"facts/CIK{cik:010d}"] = self.fetch(url, issuer=symbol, optional=True, cap=16 * 1024 * 1024)
                self.observations[f"facts/CIK{cik:010d}"] = dict(self.observations["http/" + url])
        extra = []
        for currency in sorted(currencies):
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(currency + 'USD=X', safe='')}?range=5d&interval=1d"
            self.plan_keys[url] = digest(("fx/" + currency).encode())
            self.plan_specs[url] = ("fx/" + currency, 8 * 1024 * 1024)
            extra.append((self.plan_keys[url], url, "fx/" + currency, 8 * 1024 * 1024))
        for symbol, slug in ranking.CISION_ISSUERS.items():
            if symbol in members:
                url = ranking.CISION_RSS.format(slug=slug)
                self.plan_keys[url] = digest(("cision/rss/" + symbol).encode())
                self.plan_specs[url] = (symbol, 8 * 1024 * 1024)
                extra.append((self.plan_keys[url], url, symbol, 8 * 1024 * 1024))
        if extra:
            self._acquire(extra, outputs, "auxiliary")
        # Discover the same newest qualifying report link as the real Cision
        # parser BEFORE it records an RSS attempt. A staged pause must never
        # consume its 20h cadence/three attempts without acquiring the bytes.
        pages = []
        for symbol, slug in ranking.CISION_ISSUERS.items():
            if symbol not in members:
                continue
            rss = self.entries.get("http/" + ranking.CISION_RSS.format(slug=slug))
            if rss:
                try:
                    items = ranking.ET.fromstring(rss.decode("utf-8-sig", "replace")).findall("./channel/item")
                    reports = [(item.findtext("title") or "", item.findtext("link") or "") for item in items
                               if ranking._REPORT_TITLE.search(item.findtext("title") or "") and
                               not re.search(r"\binvitation\b", item.findtext("title") or "", re.I)]
                    link = reports[0][1] if reports else ""
                    if link.startswith("https://news.cision.com/"):
                        slot = digest(("cision/report/" + symbol).encode())
                        self.plan_keys[link], self.plan_specs[link] = slot, (symbol, 8 * 1024 * 1024)
                        pages.append((slot, link, symbol, 8 * 1024 * 1024))
                except ranking.ET.ParseError:
                    pass  # actual malformed optional feed, never progress/quota success
        if pages:
            self._acquire(pages, outputs, "cision-pages")
        for currency in currencies:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(currency + 'USD=X', safe='')}?range=5d&interval=1d"
            self.entries["fx/" + currency] = self.fetch(url, issuer="fx/" + currency, optional=True)
            self.observations["fx/" + currency] = dict(self.observations["http/" + url])
        self.owner.remaining()
        return reference_day.date()

    def _acquire(self, plan, outputs, name):
        # Stable fair progress even across a changed calendar URL or optional
        # failures. Request budget is the ORIGINAL lease's shrinking shared cap;
        # never create a replacement lease/reset quotas to finish a prefix.
        if not plan or len(plan) > 1024:
            raise HostUnavailable("ACQUISITION_PLAN_BOUND")
        # Independent stable cursors, not a single last-plan value. Day-window
        # URL changes cannot reset the fair position or overwrite another stage.
        plan_id = digest(("guidance-acquisition-v2/" + name).encode())
        cursor = outputs.progress(plan_id, len(plan))
        complete, last = True, cursor
        self.progress_state = {"Stage": name, "Cursor": cursor, "Slots": len(plan)}
        self.network_allowed = True
        try:
            for offset in range(len(plan)):
                position = (cursor + offset) % len(plan)
                slot, url, issuer, cap = plan[position]
                self.plan_keys[url] = slot
                cached = outputs.captured_public(slot, url, now(), 20 if urlsplit(url).hostname == "data.sec.gov" else 3)
                work = getattr(self.owner.lease, "_network_work", {"requests": 0, "issuers": {}})
                batch_bytes = sum(len(row[2]) if row[2] is not None else 0 for row in self.batch)
                if cached is None and (work["requests"] >= 112 or work["issuers"].get(issuer, 0) >= 24 or
                        batch_bytes >= 8 * 1024 * 1024 or self.owner.remaining() < 35):
                    complete = False
                    last = position
                    break  # leave 8 shared requests for actual dynamic builder channels
                self.fetch(url, issuer=issuer, optional=True, cap=cap)
                last = (position + 1) % len(plan)
        finally:
            self.network_allowed = False
        outputs.capture_batch(self.batch, plan_id, last)
        self.batch.clear()
        self.progress_state["Cursor"] = last
        if not complete:
            raise _AcquisitionDeferred()

    def dynamic_fetch(self, url):
        # Material configured channels were all planned. A future real-builder
        # extension may not silently drop an input or swallow a control fault.
        self.network_allowed = True
        try:
            issuer, cap = self.plan_specs.get(url, ("dynamic/" + str(urlsplit(url).hostname), 8 * 1024 * 1024))
            if "http/" + url not in self.entries and self.owner.remaining() < 35:
                self.progress_state = {"Stage": "dynamic", "Cursor": 0, "Slots": 1}
                raise _AcquisitionDeferred()
            return self.fetch(url, issuer=issuer, optional=True, cap=cap)
        except Exception:
            # Optional DNS/read/HTTP absence is already a typed None observation
            # inside fetch. All remaining exceptions are genuine control faults.
            raise _CaptureControlFault() from None
        finally:
            self.network_allowed = False

    def flush(self):
        if self.batch:
            self.outputs.capture_batch(self.batch, None, None)
            self.batch.clear()

    def require_observation_times(self, cutoff):
        for key, observed in self.observations.items():
            if not key.startswith("http/"):
                continue
            stamp = observed.get("claimed_retrieved_at") or observed.get("observed_at")
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            maximum = 20 if urlsplit(key[5:]).hostname == "data.sec.gov" else 3
            if not 0 <= (cutoff - moment).total_seconds() <= maximum * 3600:
                raise HostUnavailable("CAPTURE_FRESHNESS_UNAVAILABLE")

    def catalog(self):
        import publish_sealed_snapshot as publisher
        return publisher.CapturedPublicationInputs(dict(self.entries))

    def manifest(self):
        return {"schema": "guidance-consumed-source-v1", "release_id": self.release_id,
                "code_sha256": self.code, "auxiliary_sha256": self.catalog().manifest(),
                "observations": self.observations}


class _LiveWitness:
    """Private live owner evidence, cannot be serialized/restored/minted by JSON."""
    __slots__ = ("owner", "snapshot", "consumption", "revision", "record", "digests", "journal_state", "source", "acked", "public_bundle")
    def __init__(self, owner, snapshot, consumption, rev, record, digests, journal_state, source, public_bundle=None):
        self.owner, self.snapshot, self.consumption, self.revision = owner, snapshot, consumption, rev
        self.record, self.digests, self.journal_state, self.source = record, digests, journal_state, source
        self.acked = False
        self.public_bundle = public_bundle  # already verified PUBLIC bytes, never serialized witness authority
    def __reduce__(self):
        raise TypeError("LIVE_WITNESS_NOT_SERIALIZABLE")


class _Session:
    def __init__(self, deadline, headers, machine_enabled=False):
        self.deadline, self.sec_headers = deadline, headers
        self.machine_enabled = machine_enabled
        self.public_export_started = self.public_export_complete = False
        self.guard, self.session_ref = object(), secrets.token_hex(24)
        self.lease = self.operation = self.version = self.version_ref = self.witness = None
        self.closed = False
        self.phase = "new"
        self.symbols = None
        self.live_owner = None

    def remaining(self):
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise HostUnavailable("REQUEST_DEADLINE")
        if self.lease is not None:
            self.lease.constrain_remaining_budget(max(1, int(left * 1000)))
        return left

    def tighten(self, frame):
        budget = frame["remaining_ms"]
        deadline_utc = datetime.fromisoformat(frame["deadline_utc"].replace("Z", "+00:00"))
        if deadline_utc.tzinfo is None:
            raise HostUnavailable("REQUEST_DEADLINE")
        left = min(budget / 1000, max(0.0, (deadline_utc - datetime.now(timezone.utc)).total_seconds()))
        self.deadline = min(self.deadline, time.monotonic() + left)

    def open(self):
        from revenue_guidance_bootstrap import acquire
        self.remaining()
        self.live_owner = provisioner.acquire_live_owner()  # fresh authority/interlock BEFORE any P2 allocation
        self.remaining()
        self.lease = acquire(max(1, int(self.remaining() * 1000)), parent_deadline=self.deadline)
        self.operation = self.lease.namespace_operation()
        self.operation.__enter__()
        origin = provisioner.controlled_origin()
        try:
            layers = strict_json(origin.files["config/bottleneck-layers-v3.json"], 8 * 1024 * 1024)["layers"]
            self.symbols = sorted({row["symbol"] for layer in layers for row in layer["capturers"]})
            if not self.symbols or len(self.symbols) > 256 or any(not SYMBOL.fullmatch(s) for s in self.symbols):
                raise HostUnavailable("RANKING_SCOPE_UNAVAILABLE")
        finally:
            origin.close()
        journal = self.lease.read_journal()
        current = self.input_revision()
        # Restart has NO private model witness. Conservatively require real
        # consumption again, including previously acknowledged writable journals.
        if journal.state["Intent"] is None and (journal.state["PendingRevision"] is None or
                journal.state["InputRevision"] != current or journal.state["PendingRevision"] != current):
            requested = {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
                         "InputRevision": current, "PendingRevision": current, "Intent": None}
            committed = self.lease.commit_journal(journal.version, requested)
            if not committed.success or committed.state != requested:
                raise HostUnavailable("OPEN_PENDING_COMMIT_UNAVAILABLE")
        self.phase = "idle"
        return {"Available": True, "SessionRef": self.session_ref}

    def snapshot(self, cutoff=None):
        store = overlay.B1Store(self.lease)  # actual recapture, no stale checker/updater epoch cache
        snapshot = overlay.require_snapshot(overlay.load_effective_inputs(
            cutoff=cutoff or now(), state_root=store, symbols=self.symbols, state_required=True))
        if snapshot.condition == "STATE_FAILURE":
            raise HostUnavailable("GUIDANCE_INPUTS_UNAVAILABLE")
        return snapshot

    def input_revision(self):
        return revision.compute_input_revision(self.snapshot())

    def bind_version(self, token):
        # Original opaque native object, not serialized/re-created. One current
        # session-bound ref; old refs expire. Issued native tokens remain native.
        self.version, self.version_ref = token, secrets.token_hex(24)
        return self.version_ref

    def journal(self):
        result = self.lease.read_journal()
        if result.state_required is not True:
            raise HostUnavailable("JOURNAL_UNINITIALIZED")
        return {"State": result.state, "VersionRef": self.bind_version(result.version)}

    def commit(self, args):
        if set(args) != {"VersionRef", "NewState"} or args["VersionRef"] != self.version_ref or self.version is None:
            raise HostUnavailable("VERSION_REFERENCE_UNAVAILABLE")
        requested = args["NewState"]
        # No arbitrary clean/ACK commit merely because its JSON is well formed.
        previous = self.lease.read_journal().state
        if type(requested) is not dict or set(requested) != {"Schema", "StateRequired", "InputRevision", "PendingRevision", "Intent"}:
            raise HostUnavailable("JOURNAL_STATE_UNAVAILABLE")
        intent = requested["Intent"]
        expected = {"Schema": "guidance-provider-journal-v1", "StateRequired": True,
                    "InputRevision": previous["InputRevision"], "PendingRevision": previous["PendingRevision"], "Intent": None}
        current = self.input_revision()
        if previous["Intent"] is None and intent is not None:
            if self.phase != "idle" or type(intent) is not dict or type(intent.get("Id")) is not str or not re.fullmatch("[0-9a-f]{32}", intent["Id"]):
                raise HostUnavailable("JOURNAL_PHASE_UNAVAILABLE")
            expected["Intent"] = {"Id": intent["Id"], "BaseInputRevision": previous["InputRevision"],
                                  "ObservedAtBeginRevision": current, "PriorPendingRevision": previous["PendingRevision"]}
            next_phase = "begun"
        elif previous["Intent"] is not None and intent is None:
            if self.phase == "idle":
                # Original P1 interrupted-intent recovery, always genuinely pending.
                expected.update(InputRevision=current, PendingRevision=current)
            elif self.phase == "updated":
                base = previous["Intent"]["BaseInputRevision"]
                if current != base:
                    expected.update(InputRevision=current, PendingRevision=current)
                elif previous["PendingRevision"] is not None and previous["PendingRevision"] != current:
                    expected["PendingRevision"] = current
            else:
                raise HostUnavailable("JOURNAL_PHASE_UNAVAILABLE")
            next_phase = "idle"
        elif previous["PendingRevision"] is not None and requested["PendingRevision"] is None:
            if not self.completion(current)["Completed"]:
                raise HostUnavailable("COMPLETION_UNAVAILABLE")
            expected["PendingRevision"] = None
            next_phase = "idle"
        else:
            raise HostUnavailable("JOURNAL_PHASE_UNAVAILABLE")
        if requested != expected or requested["StateRequired"] is not True:
            raise HostUnavailable("JOURNAL_STATE_UNAVAILABLE")
        self.phase = "dispatching"
        result = self.lease.commit_journal(self.version, requested)
        ref = self.bind_version(result.version)
        if result.success and result.state == requested:
            self.phase = next_phase
            if self.witness is not None and requested.get("PendingRevision") is None:
                self.witness.acked = True
                self.witness.journal_state = result.state
        else:
            self.phase = "failed"
        return {"Committed": result.success, "State": result.state, "VersionRef": ref}

    def check(self):
        if self.phase != "begun":
            raise HostUnavailable("SESSION_PHASE_UNAVAILABLE")
        import revenue_guidance_release_check as checker
        self.phase = "dispatching"
        store = overlay.B1Store(self.lease)
        result = checker.run(None, store / "receipts.json", now(), state_root=store,
                             network=checker.ReceiptTransport(store, self.sec_headers))
        succeeded = result["status"] == "OK"
        self.phase = "checked" if succeeded else "failed"
        return {"Succeeded": succeeded, "Reason": "CHECK_RELEASE_RESULT"}

    def update(self):
        if self.phase != "checked":
            raise HostUnavailable("SESSION_PHASE_UNAVAILABLE")
        import revenue_guidance_autoupdate as updater
        self.phase = "dispatching"
        result = updater.run(overlay.B1Store(self.lease), updater.Transport(self.sec_headers), now)
        succeeded = result["status"] == "OK"
        self.phase = "updated" if succeeded else "failed"
        return {"Succeeded": succeeded, "Reason": "UPDATE_RESULT"}

    def rank(self, args):
        if set(args) != {"Mode", "Revision"} or args["Mode"] not in ("Dirty", "Cadence") or self.phase != "idle":
            raise HostUnavailable("RANKING_PHASE_UNAVAILABLE")
        state = self.lease.read_journal().state
        rev = self.input_revision()
        if state["Intent"] is not None or state["StateRequired"] is not True or state["InputRevision"] != rev:
            raise HostUnavailable("RANKING_REVISION_UNAVAILABLE")
        if state["PendingRevision"] is None:
            # Only an unchanged ALREADY-live witnessed result may meet cadence;
            # never claim a cached ranking consumed a newly acquired snapshot.
            if (args["Mode"] != "Cadence" or self.witness is None or not self.witness.acked or
                    self.witness.owner is not self.guard or now() - datetime.fromisoformat(self.witness.snapshot.cutoff.replace("Z", "+00:00")) >= timedelta(hours=3)):
                raise HostUnavailable("LIVE_REBUILD_REQUIRED")
            self._read_witness(self.witness, state)
            return {"Completed": True, "Revision": rev, "ReusedLiveConsumption": True}
        if state["PendingRevision"] != rev or args["Revision"] != rev or not GIR.fullmatch(rev):
            raise HostUnavailable("RANKING_REVISION_UNAVAILABLE")
        import bottleneck_top20_v3 as ranking
        import publish_sealed_snapshot as publisher
        outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
        captured = _Capture(self)
        self.witness = None
        self.phase = "dispatching"
        try:
            planning_day = captured.collect(outputs)
            cutoff = now()  # actual whole UTC second, the exact ranking/model cutoff
            if cutoff.date() != planning_day:
                raise HostUnavailable("CAPTURE_DAY_CHANGED")
            captured.require_observation_times(cutoff)
            ranking_doc = ranking.build(captured.dynamic_fetch, cutoff, with_news=True,
                                        captured=captured.catalog(), cision_outputs=outputs)
            captured.flush()
            ranking_bytes = encoded(ranking_doc)
            if ranking_doc["generated_at"] != cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"):
                raise HostUnavailable("RANKING_CUTOFF_MISMATCH")
            # Symbols resolve from the actual build, within the SAME canonical
            # protected universe used by every ReadInputRevision (gir1 includes it).
            actual_symbols = [entry["symbol"] for entry in ranking_doc["top"]]
            snapshot = self.snapshot(cutoff)
            if revision.compute_input_revision(snapshot) != rev or any(symbol not in snapshot.symbols() for symbol in actual_symbols):
                raise HostUnavailable("MODEL_INPUT_REVISION_MISMATCH")
            consumption = publisher.ForecastConsumption(snapshot)
            machine_inputs = None
            if self.machine_enabled:
                import revenue_guidance_machine as machine
                machine_inputs = machine.resolve_machine_inputs(snapshot, cutoff, tuple(actual_symbols))
            bodies = publisher.captured_bottleneck_v3_body(ranking_bytes, cutoff, snapshot,
                        captured=captured.catalog(), consumption=consumption,
                        guidance_machine_enabled=self.machine_enabled, machine_inputs=machine_inputs)
            body_text = bodies.get(publisher.BOTTLENECK_V3_KEY)
            if not body_text or not 10 <= len(actual_symbols) <= 20 or len(set(actual_symbols)) != len(actual_symbols):
                raise HostUnavailable("SEALED_OUTPUT_UNAVAILABLE")
            if [row[0] for row in consumption.rows] != actual_symbols or consumption.snapshot is not snapshot:
                raise HostUnavailable("MODEL_CONSUMPTION_MISMATCH")
            body = body_text.encode("utf-8")
            if len(body) > 1900000:
                raise HostUnavailable("SEALED_OUTPUT_BOUND")
            source = captured.manifest()  # same actual consumed bytes, never hash-after-reopen
            record_doc = {"schema": "guidance-local-completion-v1", "revision": rev,
                "cutoff": snapshot.cutoff, "input_digest": snapshot.input_digest,
                "generation_id": snapshot.generation_id, "generation_sha256": snapshot.generation_sha256,
                "ranking_sha256": digest(ranking_bytes), "output_sha256": digest(body),
                "source_manifest": source, "source_manifest_sha256": digest(encoded(source)),
                "model_returns": consumption.rows}
            binding = None
            if self.machine_enabled:
                binding = machine.make_public_binding(machine_inputs, body, rev, encoded(source))
                machine.validate_public_bundle(body, binding, digest(body), digest(binding))
                record_doc.update(public_binding_utf8=binding.decode("utf-8"), public_binding_sha256=digest(binding))
            record = encoded(record_doc)  # bounded binding embedded; no new overlay artifact kind
            self.remaining()
            if self.lease.read_journal().state != state or self.input_revision() != rev:
                raise HostUnavailable("COMPLETION_BINDING_CHANGED")
            published = outputs.publish(ranking_bytes, body, record)
            if published != {"rank": digest(ranking_bytes), "body": digest(body), "record": digest(record)}:
                raise HostUnavailable("OUTPUT_READBACK_UNAVAILABLE")
            # No witness until independent origin cleanup also confirmed. Unknown
            # origin stays in r2 custody; never acknowledge before that boundary.
            captured.close()
            self.remaining()
            if self.lease.read_journal().state != state or self.input_revision() != rev:
                raise HostUnavailable("COMPLETION_BINDING_CHANGED")
            self.witness = _LiveWitness(self.guard, snapshot, consumption, rev, record, published, state, source,
                                        None if binding is None else (body, binding))
            self.phase = "idle"
            return {"Completed": True, "Revision": rev, "ReusedLiveConsumption": False}
        except _AcquisitionDeferred:
            captured.flush()  # only confirmed actual observations/progress are durable
            captured.close()
            self.remaining()
            if self.lease.read_journal().state != state or self.input_revision() != rev:
                raise HostUnavailable("ACQUISITION_BINDING_CHANGED")
            self.phase = "idle"  # known paused acquisition, never witness/ACK/model completion
            return {"Completed": False, "Revision": rev, "AcquisitionProgress": True,
                    "Progress": captured.progress_state, "Reason": "ACQUISITION_PENDING"}
        finally:
            captured.close()
            if self.phase == "dispatching":
                self.phase = "failed"

    def _read_witness(self, witness, state):
        if witness.owner is not self.guard or state != witness.journal_state or self.input_revision() != witness.revision:
            raise HostUnavailable("COMPLETION_BINDING_CHANGED")
        snapshot = self.snapshot(datetime.fromisoformat(witness.snapshot.cutoff.replace("Z", "+00:00")))
        if (snapshot.input_digest != witness.snapshot.input_digest or snapshot.generation_id != witness.snapshot.generation_id
                or snapshot.generation_sha256 != witness.snapshot.generation_sha256
                or revision.compute_input_revision(snapshot) != witness.revision):
            raise HostUnavailable("COMPLETION_BINDING_CHANGED")
        outputs = overlay.B1Outputs(overlay.B1Store(self.lease))
        record = outputs.read("record", witness.digests["record"])
        ranking = outputs.read("rank", witness.digests["rank"])
        body = outputs.read("body", witness.digests["body"])
        if record != witness.record or digest(ranking) != witness.digests["rank"] or digest(body) != witness.digests["body"]:
            raise HostUnavailable("COMPLETION_READBACK_UNAVAILABLE")
        parsed = strict_json(record, 8 * 1024 * 1024)
        if parsed["source_manifest"] != witness.source or parsed["model_returns"] != [list(row) for row in witness.consumption.rows]:
            raise HostUnavailable("COMPLETION_SOURCE_CHANGED")
        if self.machine_enabled:
            import revenue_guidance_machine as machine
            binding = parsed["public_binding_utf8"].encode("utf-8")
            if witness.public_bundle != (body, binding) or digest(binding) != parsed["public_binding_sha256"]:
                raise machine.MachinePublicationBlocked("MACHINE_EXPORT_UNAVAILABLE")
            public = machine.validate_public_bundle(body, binding, witness.digests["body"], parsed["public_binding_sha256"])
            if public["source_manifest_sha256"] != parsed["source_manifest_sha256"]:
                raise machine.MachinePublicationBlocked("MACHINE_EXPORT_UNAVAILABLE")

    def completion(self, rev):
        absent = {"Completed": False, "Revision": rev}
        if self.phase != "idle" or type(rev) is not str or not GIR.fullmatch(rev) or self.witness is None:
            return absent
        state = self.lease.read_journal().state
        if (state["StateRequired"] is not True or state["Intent"] is not None or state["InputRevision"] != rev or
                state["PendingRevision"] != rev or self.witness.revision != rev or self.witness.acked):
            return absent
        self._read_witness(self.witness, state)
        return {"Completed": True, "Revision": rev}

    def export_public(self):
        import revenue_guidance_machine as machine
        if (not self.machine_enabled or self.public_export_started or self.phase != "idle" or
                self.witness is None or self.witness.public_bundle is None):
            raise machine.MachinePublicationBlocked("MACHINE_EXPORT_UNAVAILABLE")
        self.public_export_started = True  # sole export attempt before any fallible readback/status handoff
        state = self.lease.read_journal().state
        self._read_witness(self.witness, state)  # SAME live native owner/model consumption, BEFORE Close
        body, binding = self.witness.public_bundle
        if len(body) > 1900000 or len(binding) > 64000 or len(body) + len(binding) > 1964000:
            raise machine.MachinePublicationBlocked("MACHINE_EVIDENCE_LIMIT")
        return {"BodyBytes": len(body), "BindingBytes": len(binding), "BodySha256": digest(body),
                "BindingSha256": digest(binding), "Cutoff": self.witness.snapshot.cutoff,
                "Revision": self.witness.revision}, body, binding

    def close(self):
        if self.closed:
            raise HostUnavailable("SESSION_CLOSED")
        if self.live_owner is not None:
            self.live_owner._host_session_custody = self  # exact lease/namespace/witness graph before fallible close admission
        self.closed = True  # sole cleanup attempt, INCLUDING machine pre-close readback; never retry
        machine_acknowledged = False
        self.sec_headers.clear()
        try:
            if self.machine_enabled and self.public_export_complete and self.witness is not None and self.witness.acked:
                self._read_witness(self.witness, self.lease.read_journal().state)
                machine_acknowledged = True  # original P1 actual CAS/readback ACK, not exported metadata authority
            self.witness = self.version = self.version_ref = None
            if windows.native_custody_status() == "UNRESOLVED":
                raise HostUnavailable("NATIVE_CUSTODY_UNRESOLVED")
            try:
                if self.operation is not None:
                    self.operation.__exit__(None, None, None)
            finally:
                if self.lease is not None and windows.native_custody_status() != "UNRESOLVED":
                    self.lease.close()
            if windows.native_custody_status() != "SETTLED":
                raise HostUnavailable("NATIVE_CUSTODY_UNRESOLVED")
            if self.live_owner is not None:
                self.live_owner.close()  # original origin r2 lifetime; interlock closes LAST
            if provisioner.origin_custody_status() != "SETTLED":
                raise HostUnavailable("ORIGIN_CUSTODY_UNRESOLVED")
            if self.live_owner is not None:
                self.live_owner._host_session_custody = None  # ONLY original full confirmed settlement
            return {"Closed": True, "Custody": "SETTLED", **(
                {"MachineAcknowledged": machine_acknowledged} if self.machine_enabled else {})}
        except BaseException:
            if self.live_owner is not None and self.live_owner.live_owner_handle is not None:
                # Failed/interruptible namespace/lease disposal cannot allow a
                # later process to replace this owner before P2 settlement.
                provisioner.retain_live_owner_custody(self.live_owner)
            raise


def serve(remaining_ms):
    """Real bounded private pipe dispatcher. Bootstrap owns OUTER r2 lifetime."""
    origin = provisioner.controlled_origin()
    try:
        # Actual inherited anonymous standard pipes only, no console/file mode or
        # caller handle number. Authority is independently established FIRST.
        c, w, k, a = origin.apis
        k.GetStdHandle.argtypes = [w.DWORD]
        k.GetStdHandle.restype = w.HANDLE
        k.GetFileType.argtypes = [w.HANDLE]
        k.GetFileType.restype = w.DWORD
        if any(k.GetFileType(k.GetStdHandle(code & 0xffffffff)) != 3 for code in (-10, -11, -12)):
            raise HostUnavailable("PRIVATE_PIPE_ENTRY_REQUIRED")
    finally:
        origin.close()
    # Dependencies are from already approved closure. -S remains set: explicit
    # fixed protected scripts only; host uses stdlib public observation, no sites.
    from sec_contact_headers import sec_identity_headers
    headers = sec_identity_headers()
    os.environ.pop("SEC_CONTACT_EMAIL", None)  # inherited contact never protocol/log/persisted
    channel_in, channel_out = sys.stdin.buffer, sys.stdout.buffer
    safe = _SafeDiagnostic(sys.stderr)
    previous_stdout, previous_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = safe
    session = None
    sequence = 0
    opened = False
    def reply(request_id, status, result=None, attempted=False):
        frame = encoded({"protocol": PROTOCOL, "id": request_id, "status": status,
                         "attempted": attempted, "result": result})
        if len(frame) > MAX_FRAME:
            raise HostUnavailable("RESPONSE_BOUND")
        channel_out.write(frame + b"\n")
        channel_out.flush()
    try:
        reply(0, "HOST_PROTOCOL_READY")
        while sequence < MAX_REQUESTS:
            raw = channel_in.readline(MAX_FRAME + 2)
            if not raw:
                break
            attempted = False
            try:
                if len(raw) > MAX_FRAME + 1 or not raw.endswith(b"\n"):
                    raise HostUnavailable("FRAME_BOUND")
                frame = strict_json(raw.rstrip(b"\n"))
                if (type(frame) is not dict or set(frame) != {"protocol", "id", "op", "session", "remaining_ms", "deadline_utc", "args"}
                        or frame["protocol"] != PROTOCOL or type(frame["id"]) is not int or frame["id"] != sequence + 1
                        or frame["op"] not in OPS or type(frame["remaining_ms"]) is not int or not 0 <= frame["remaining_ms"] <= 600000
                        or type(frame["deadline_utc"]) is not str or len(frame["deadline_utc"]) > 40 or type(frame["args"]) is not dict):
                    raise HostUnavailable("FRAME_REFUSED")
                sequence = frame["id"]
                op, args = frame["op"], frame["args"]
                expected_keys = ({"VersionRef", "NewState"} if op == "CommitJournal" else
                                 {"Mode", "Revision"} if op == "RankAndComplete" else
                                 {"Revision"} if op == "ReadRebuildCompletion" else
                                 ({"GuidanceMachineEnabled"} if args else set()) if op == "Open" else set())
                if set(args) != expected_keys:
                    raise HostUnavailable("OPERATION_REFUSED")
                if op == "CommitJournal" and (type(args["VersionRef"]) is not str or
                        not re.fullmatch("[0-9a-f]{48}", args["VersionRef"]) or type(args["NewState"]) is not dict):
                    raise HostUnavailable("OPERATION_REFUSED")
                if op == "ReadRebuildCompletion" and (type(args["Revision"]) is not str or not GIR.fullmatch(args["Revision"])):
                    raise HostUnavailable("OPERATION_REFUSED")
                if op == "RankAndComplete" and (args["Mode"] not in ("Dirty", "Cadence") or
                        (args["Revision"] is not None and (type(args["Revision"]) is not str or not GIR.fullmatch(args["Revision"])))):
                    raise HostUnavailable("OPERATION_REFUSED")
                if op == "Open":
                    if (opened or frame["session"] is not None or frame["remaining_ms"] <= 0 or
                            (args and type(args["GuidanceMachineEnabled"]) is not bool)):
                        raise HostUnavailable("SESSION_REFUSED")
                    opened = True
                    session = _Session(time.monotonic() + min(remaining_ms, frame["remaining_ms"]) / 1000, headers,
                                       args.get("GuidanceMachineEnabled", False))
                    session.tighten(frame)
                    attempted = True
                    result = session.open()
                else:
                    if session is None or session.closed or frame["session"] != session.session_ref:
                        raise HostUnavailable("SESSION_REFERENCE_UNAVAILABLE")
                    if op != "Close":
                        session.tighten(frame)
                        session.remaining()
                        if session.phase in ("dispatching", "failed"):
                            raise HostUnavailable("SESSION_PHASE_UNAVAILABLE")
                    attempted = True
                    if op == "ReadJournal" and not args:
                        result = session.journal()
                    elif op == "ReadInputRevision" and not args:
                        result = {"Revision": session.input_revision()}
                    elif op == "CommitJournal":
                        result = session.commit(args)
                    elif op == "CheckRelease" and not args:
                        result = session.check()
                    elif op == "Update" and not args:
                        result = session.update()
                    elif op == "RankAndComplete":
                        result = session.rank(args)
                    elif op == "ReadRebuildCompletion" and set(args) == {"Revision"}:
                        result = session.completion(args["Revision"])
                    elif op == "ExportPublicBundle" and not args:
                        metadata, body, binding = session.export_public()
                        reply(sequence, "PUBLIC_DATA_BEGIN", metadata, attempted)
                        chunks = 0
                        for name, payload in (("body", body), ("binding", binding)):
                            for offset in range(0, len(payload), 8192):
                                session.remaining()
                                part = payload[offset:offset + 8192]
                                data_frame = encoded({"protocol": PROTOCOL, "id": sequence, "status": "PUBLIC_DATA",
                                    "object": name, "offset": offset, "chunk": chunks,
                                    "bytes": len(part), "data": base64.b64encode(part).decode("ascii")})
                                if chunks >= 256 or len(data_frame) > MAX_FRAME:
                                    raise HostUnavailable("PUBLIC_DATA_BOUND")
                                channel_out.write(data_frame + b"\n")
                                channel_out.flush()
                                chunks += 1
                        session._read_witness(session.witness, session.lease.read_journal().state)
                        result = {"Exported": True, "Chunks": chunks, **metadata}
                    elif op == "Close" and not args:
                        result = session.close()
                    else:
                        raise HostUnavailable("OPERATION_REFUSED")
                if safe.observed:
                    raise HostUnavailable("HOST_LIBRARY_DIAGNOSTIC")
                reply(sequence, "OK", result, attempted)
                if op == "ExportPublicBundle":
                    session.public_export_complete = True  # terminal confirmation flushed, no private witness exported
                if op == "Close":
                    return 0
            except BaseException as error:
                machine_reason = None
                if session is not None and session.machine_enabled:
                    import revenue_guidance_machine as machine
                    if isinstance(error, machine.MachinePublicationBlocked):
                        machine_reason = error.reason
                if session is not None and attempted:
                    session.phase = "failed"
                if windows.native_custody_status() == "UNRESOLVED":
                    reply(sequence, "NATIVE_CUSTODY_UNRESOLVED", None, attempted)
                    windows.hold_unresolved_native_custody()  # actual same-domain owner; never exit/kill/ack
                reply(sequence, "HOST_OPERATION_UNAVAILABLE" if attempted else "REFUSED_BEFORE_DISPATCH",
                      None if machine_reason is None else {"Reason": machine_reason}, attempted)
                if attempted:
                    break  # terminal uncertain/failed operation; never retry it
        return 2
    except BaseException:
        # No raw traceback, no error/path/payload/contact output. Actual lifetime
        # is decided below and AGAIN by bootstrap's outer r2 finally.
        return 2
    finally:
        headers.clear()
        try:
            if session is not None and not session.closed and windows.native_custody_status() != "UNRESOLVED":
                session.close()  # observed settled EOF/failure, at most once
        finally:
            sys.stdout, sys.stderr = previous_stdout, previous_stderr
            if windows.native_custody_status() == "UNRESOLVED":
                windows.hold_unresolved_native_custody()

"""Independent ranking cadence and conservative UTC-day KV reservations.

Reserve each product's ENTIRE retry-inclusive plan before a controlled PUT. The
fixed partitions are 400 ranking and 600 market/identity attempts, so their sum
cannot exceed the shared 1000 limit. At UTC rollover reserve the full remaining
plan in both partitions before the next launch; never refund unused retries.
Unknown ledgers fail closed. Stopped days expire automatically at 00:00 UTC.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_SECONDS = 21600
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.^=-]{0,15}\Z")


def _utc(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("RANKING_CLOCK_INVALID")
    return now.astimezone(timezone.utc)


def _generated(doc: dict) -> datetime:
    value = doc.get("generated_at", doc.get("asof_utc"))
    if not isinstance(value, str):
        raise ValueError("RANKING_CLOCK_INVALID")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError("RANKING_CLOCK_INVALID") from None


def ordered_rank_digest(doc: dict) -> str:
    """Commit only the 10–20 distinct ordered symbols, never scores or inputs."""
    if not isinstance(doc, dict):
        raise ValueError("RANKING_TOP_INVALID")
    rows = doc.get("top", doc.get("records", doc.get("ranked")))
    if not isinstance(rows, list) or not 10 <= len(rows) <= 20:
        raise ValueError("RANKING_TOP_INVALID")
    symbols = [row.get("symbol", row.get("ticker")) if isinstance(row, dict) else row for row in rows]
    if (any(not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in symbols)
            or len(set(symbols)) != len(symbols)):
        raise ValueError("RANKING_TOP_INVALID")
    return hashlib.sha256(json.dumps(symbols, separators=(",", ":")).encode("ascii")).hexdigest()


def publication_due(previous: dict | None, candidate: dict, now: datetime) -> str:
    now = _utc(now)
    current_digest = ordered_rank_digest(candidate)
    if _generated(candidate) > now:
        raise ValueError("RANKING_CLOCK_FUTURE")
    if previous is None:
        return "INITIAL"
    prior_digest = ordered_rank_digest(previous)
    prior_time = _generated(previous)
    if prior_time > now or _generated(candidate) < prior_time:
        raise ValueError("RANKING_CLOCK_FUTURE")
    if current_digest != prior_digest:
        return "CHANGED"
    return "HEARTBEAT" if (now - prior_time).total_seconds() >= HEARTBEAT_SECONDS else "NO_CHANGE"


def _safe_path(path: Path) -> None:
    absolute = path.absolute()
    for item in reversed((absolute, *absolute.parents)):
        try:
            meta = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(meta.st_mode) or getattr(meta, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("RANKING_BUDGET_UNSAFE_PATH")
    if path.exists() and not path.is_file():
        raise ValueError("RANKING_BUDGET_UNSAFE_PATH")


@contextmanager
def _locked(path: Path, *, create: bool = True):
    _safe_path(path)
    fd = os.open(str(path), (os.O_CREAT if create else 0) | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if create and os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class DailyWriteBudget:
    """Durable reservation ledger. Construction and cadence reads never initialize it."""
    def __init__(self, path: Path, *, daily_limit: int = 1000, reserve: int = 600):
        if (type(daily_limit) is not int or type(reserve) is not int
                or not 0 <= reserve <= daily_limit):
            raise ValueError("RANKING_BUDGET_LIMIT_INVALID")
        self.path = Path(path)
        self.daily_limit = daily_limit
        self.other_products_reserve = reserve
        self.allowance = daily_limit - reserve
        self._stopped_day = None

    def _load(self, day: str) -> dict:
        _safe_path(self.path)
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4097)
        except FileNotFoundError:
            return {"schema": "ranking-kv-budget-v1", "day": day, "reserved": 0, "stopped": False}
        if len(raw) > 4096:
            raise ValueError("RANKING_BUDGET_INVALID")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("RANKING_BUDGET_INVALID")
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=pairs)
        if (not isinstance(value, dict) or set(value) != {"schema", "day", "reserved", "stopped"}
                or value["schema"] != "ranking-kv-budget-v1" or not isinstance(value["day"], str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["day"])
                or type(value["reserved"]) is not int or value["reserved"] < 0
                or type(value["stopped"]) is not bool or value["day"] > day):
            raise ValueError("RANKING_BUDGET_INVALID")
        datetime.fromisoformat(value["day"])  # Impossible calendar days cannot reset the allowance.
        if value["day"] < day:
            return {"schema": "ranking-kv-budget-v1", "day": day, "reserved": 0, "stopped": False}
        return value

    def _save(self, value: dict) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp", delete=False) as stream:
                name = stream.name
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            name = None
            if os.name != "nt":
                fd = os.open(str(self.path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if name is not None:
                os.unlink(name)

    def can_reserve(self, count: int, now: datetime) -> bool:
        """Read-only advisory preflight; reserve() is still the sole authorization."""
        if type(count) is not int or count <= 0:
            raise ValueError("RANKING_BUDGET_COUNT_INVALID")
        day = _utc(now).date().isoformat()
        if self._stopped_day == day:
            return False
        try:
            _safe_path(self.path)
            lock = self.path.with_name(self.path.name + ".lock")
            _safe_path(lock)
            if not lock.exists():
                # No ledger may be admitted without its stable locking inode.
                return not self.path.exists() and count <= self.allowance
            with _locked(lock, create=False):
                value = self._load(day)
                return not value["stopped"] and value["reserved"] + count <= self.allowance
        except (OSError, ValueError, UnicodeError):
            return False

    def reserve(self, count: int, now: datetime) -> bool:
        if type(count) is not int or count <= 0:
            raise ValueError("RANKING_BUDGET_COUNT_INVALID")
        day = _utc(now).date().isoformat()
        if self._stopped_day == day:
            return False
        try:
            _safe_path(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _locked(self.path.with_name(self.path.name + ".lock")):
                value = self._load(day)
                if value["stopped"] or value["reserved"] + count > self.allowance:
                    return False
                value["reserved"] += count
                self._save(value)
                return True
        except (OSError, ValueError, UnicodeError):
            return False  # No remote attempt is authorized by an uncertain local write.

    def stop_until_reset(self, now: datetime) -> None:
        day = _utc(now).date().isoformat()
        self._stopped_day = day
        try:
            _safe_path(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _locked(self.path.with_name(self.path.name + ".lock")):
                value = self._load(day)
                value["stopped"] = True
                self._save(value)
        except (OSError, ValueError, UnicodeError):
            pass  # Subsequent reservations still fail closed for unknown/busy state.


class DailyWriteReservation:
    """Retry-inclusive remaining plan, authorized again at each UTC-day boundary.

    Slots count controlled CLI launches, not an asserted provider HTTP count.
    Finishing an operation retires unused retries from the remaining plan only;
    it never refunds the durable daily reservation.
    """

    def __init__(self, budget: DailyWriteBudget, count: int):
        if type(count) is not int or count <= 0:
            raise ValueError("RANKING_BUDGET_COUNT_INVALID")
        self.budget = budget
        self.remaining = count
        self.reserved = 0
        self.day = None

    def authorize(self, now: datetime) -> bool:
        day = _utc(now).date().isoformat()
        if self.remaining <= 0 or self.day is not None and day < self.day:
            return False
        if day == self.day:
            return True
        if not self.budget.reserve(self.remaining, now):
            return False
        self.day = day
        self.reserved += self.remaining
        return True

    def launch(self, now: datetime) -> bool:
        """Consume one slot only after the full remaining plan is authorized."""
        if not self.authorize(now):
            return False
        self.remaining -= 1
        return True

    def retire(self, count: int) -> None:
        """Drop unused retry slots; durable reservations remain conservative."""
        if type(count) is not int or not 0 <= count <= self.remaining:
            raise ValueError("RANKING_BUDGET_COUNT_INVALID")
        self.remaining -= count


class PublicationWriteBudget:
    """Two fixed durable partitions; neither can borrow the other's allowance."""

    def __init__(self, ranking_path: Path):
        self.parts = {
            "ranking": DailyWriteBudget(ranking_path),
            "market": DailyWriteBudget(Path(ranking_path).with_name("market-kv-write-budget.json"), reserve=400),
        }

    def can_reserve(self, counts: dict[str, int], now: datetime) -> bool:
        return all(count == 0 or self.parts[name].can_reserve(count, now)
                   for name, count in _publication_counts(counts).items())

    def stop_until_reset(self, now: datetime) -> None:
        # A provider-wide limit halts both partitions, not only the failed key.
        for budget in self.parts.values():
            budget.stop_until_reset(now)


def _publication_counts(counts: dict[str, int]) -> dict[str, int]:
    if (not isinstance(counts, dict) or not set(counts) <= {"ranking", "market"}
            or any(type(count) is not int or count < 0 for count in counts.values())):
        raise ValueError("PUBLICATION_BUDGET_COUNT_INVALID")
    return {name: counts.get(name, 0) for name in ("ranking", "market")}


class PublicationWriteReservation:
    """Authorize both remaining partitions before every PUT, including retries."""

    def __init__(self, budget: PublicationWriteBudget, counts: dict[str, int]):
        counts = _publication_counts(counts)
        if not any(counts.values()):
            raise ValueError("PUBLICATION_BUDGET_COUNT_INVALID")
        self.parts = {name: DailyWriteReservation(budget.parts[name], count)
                      for name, count in counts.items() if count}
        self.attempted = {"ranking": 0, "market": 0}
        self.selected = "ranking" if "ranking" in self.parts else "market"

    @property
    def remaining(self) -> int:
        return sum(part.remaining for part in self.parts.values())

    @property
    def reserved(self) -> int:
        return sum(part.reserved for part in self.parts.values())

    @property
    def reserved_by_product(self) -> dict[str, int]:
        return {name: self.parts[name].reserved if name in self.parts else 0
                for name in ("ranking", "market")}

    def select(self, product: str) -> None:
        if product not in self.parts:
            raise ValueError("PUBLICATION_BUDGET_PRODUCT_INVALID")
        self.selected = product

    def authorize(self, now: datetime) -> bool:
        # Failed second-part authorization never refunds the first reservation.
        # Preflight avoids this in the single-writer path; races remain bounded.
        return all(part.remaining == 0 or part.authorize(now) for part in self.parts.values())

    def launch(self, now: datetime) -> bool:
        if not self.authorize(now) or not self.parts[self.selected].launch(now):
            return False
        self.attempted[self.selected] += 1
        return True

    def retire(self, count: int) -> None:
        self.parts[self.selected].retire(count)

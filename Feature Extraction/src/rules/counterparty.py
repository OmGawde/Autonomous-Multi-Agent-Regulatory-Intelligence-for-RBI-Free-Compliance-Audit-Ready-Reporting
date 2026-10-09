"""
Counterparty identity and the learned override registry.

Two jobs that must stay separate from `merchant_entity`:

1. **A stable identity key.** Banks truncate the payee field at a fixed width and
   the width differs per bank and per rail -- ICICI cuts BIL/NEFT at 10
   characters, Axis UPI at 9 or 21 depending on which of its two co-existing
   schemas emitted the row, SBI UPI at 8. The same person therefore appears as
   `GIRISH BAB`, `GIRISH B` and `GIRISH BABAJI G` across statements, and exact
   matching finds none of them (measured: 0 exact cross-bank matches, 4 by
   prefix). The key normalises whitespace, case and punctuation, and matching is
   prefix-based.

2. **Learned labels.** Some purposes are simply not in the file -- a Rs 1,300
   monthly NEFT to a co-operative bank is housing-society maintenance, and no
   amount of parsing will say so. Once a human names a counterparty, that name
   should hold for every future statement.

**Why this is not `merchant_entity`.** An earlier attempt normalised
`merchant_entity` in place. Merging a payer's regular monthly credit with their
ad-hoc transfers pushed the group's amount variance past the salary detector's
threshold, and detected income on one statement fell from Rs 1,20,766 to Rs 766.
Grouping and overrides use `counterparty_key`; income detection keeps reading the
untouched `merchant_entity`.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# configs/ is the writable, pipeline-owned directory both the standalone
# pipeline and the web backend already agree on. Deliberately NOT inside
# rules_config.json: ConfigManager is a singleton with no reload path, so a
# long-running API process would never observe a write.
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "configs" / "counterparty_overrides.json"

_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_SPACE = re.compile(r"\s+")
# Corporate suffixes carry no identifying information and differ between
# statements of the same counterparty.
# Bare "CO" is deliberately absent: it would turn "ABHYUDAYA CO-OP" into
# "ABHYUDAYA OP" and destroy the co-operative-bank marker, which is part of the
# grouping key for short truncated names.
_SUFFIXES = re.compile(
    r"\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP|COMPANY|THE)\b"
)
_VPA = re.compile(r"([A-Za-z0-9._-]+)@([A-Za-z]+)")

MIN_KEY_LENGTH = 4
MIN_PREFIX_MATCH = 6


def normalise_name(value: str) -> str:
    """Upper-case, strip punctuation and corporate suffixes, collapse spaces.

    Whitespace collapsing matters more than it looks: ICICI's text layer emits
    both `ST ATE BANK OF I` and `STATE BANK OF I`, which silently split a
    Rs 4,00,000 counterparty group in two.
    """
    if not value:
        return ""
    text = _PUNCT.sub(" ", str(value).upper())
    text = _SUFFIXES.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def extract_vpa(description: str) -> str:
    """Local part of the first UPI VPA in the narration, normalised.

    The VPA survives truncation better than the payee on several banks and is
    the strongest bridge between statements -- `ggidaye@oksbi` in one and
    `ggidaye@ok` in another are the same handle.
    """
    m = _VPA.search(str(description or ""))
    if not m:
        return ""
    local = m.group(1)
    # Strip the trailing disambiguators banks append (-1, .2)
    local = re.sub(r"[-._]\d+$", "", local)
    return normalise_name(local).replace(" ", "")


def build_counterparty_key(
    *,
    payee: str = "",
    description: str = "",
    merchant_entity: str = "",
    counterparty_bank: str = "",
) -> str:
    """
    Build a stable identity key for a counterparty.

    Preference order: a canonical merchant name (already resolved and not
    truncated), then the VPA local part, then the raw payee. The counterparty
    bank is appended only when the name is short enough to be ambiguous.
    """
    entity = normalise_name(merchant_entity)
    if entity and len(entity) >= MIN_KEY_LENGTH and not entity.isdigit():
        return entity

    vpa = extract_vpa(description)
    if vpa and len(vpa) >= MIN_KEY_LENGTH:
        return vpa

    name = normalise_name(payee)
    if not name or len(name) < MIN_KEY_LENGTH or name.replace(" ", "").isdigit():
        return ""

    # Spaces are collapsed out of the bank portion: ICICI's text layer emits
    # both "ST ATE BANK OF I" and "STATE BANK OF I" for the same bank, which
    # silently split a Rs 4,00,000 counterparty group in two.
    bank = normalise_name(counterparty_bank).replace(" ", "")
    if bank and len(name) <= 10:
        # Short (truncated) names need the bank to disambiguate.
        return f"{name}|{bank}"
    return name


def keys_match(a: str, b: str) -> bool:
    """True if two counterparty keys plausibly denote the same party.

    Prefix matching, because truncation is the dominant failure mode: exact
    matching finds 0 of the 4 known cross-bank pairs.
    """
    if not a or not b:
        return False
    left, right = a.split("|")[0].replace(" ", ""), b.split("|")[0].replace(" ", "")
    if left == right:
        return True
    if min(len(left), len(right)) < MIN_PREFIX_MATCH:
        return False
    return left.startswith(right) or right.startswith(left)


def canonicalise_keys(keys: List[str]) -> Dict[str, str]:
    """
    Collapse truncation variants onto their longest spelling.

    `FAIZ AQEE` and `FAIZ AQEEL QURESHI` are one person split by Axis's two UPI
    schemas (9 and 21 characters); this maps both to the longer form.
    """
    canonical: Dict[str, str] = {}
    for key in sorted({k for k in keys if k}, key=len, reverse=True):
        for existing in canonical.values():
            if keys_match(key, existing):
                canonical[key] = existing
                break
        else:
            canonical[key] = key
    return canonical


# ============================================================
# Self-transfer detection
# ============================================================

# Honorifics and relationship words that appear in payee fields and must not be
# treated as part of the name when comparing against the account holder.
_TITLES = re.compile(r"\b(MR|MRS|MS|MISS|DR|SHRI|SMT|SRI|PROF)\b")


def _name_tokens(value: str) -> List[str]:
    """Meaningful name tokens, longest first."""
    cleaned = _TITLES.sub(" ", normalise_name(value))
    return [t for t in cleaned.split() if len(t) >= 3]


def is_self_transfer(
    *,
    account_holder: str,
    payee: str = "",
    description: str = "",
    counterparty_key: str = "",
) -> tuple:
    """
    Decide whether a transfer is between the account holder's own accounts.

    This is not cosmetic. On one real statement the entire detected income was
    recurring NEFT from a counterparty sharing the holder's surname -- if that is
    the holder's own second account, the "income" is a self-transfer and the
    figure is wrong. So this runs before income detection.

    Signals, strongest first:
      1. the holder's full name (or a distinctive token of it) appears in the
         payee field
      2. the UPI VPA local part contains a distinctive token of the holder's name

    With no account-holder name supplied we return False rather than guess --
    "same surname" alone is a family member at least as often as it is a second
    account.

    Returns (is_self, reason).
    """
    if not account_holder:
        return False, ""

    holder_tokens = _name_tokens(account_holder)
    if not holder_tokens:
        return False, ""

    # Every token of a usable length counts. Taking only "the two longest"
    # silently dropped the surname whenever the name parts were the same length
    # -- GIRISH / BABAJI / GIDAYE are all six characters, so the surname that
    # actually appears in the UPI handle was the one discarded.
    distinctive = [t for t in holder_tokens if len(t) >= 4]

    payee_norm = normalise_name(payee)
    payee_tokens = _name_tokens(payee)

    # Truncation means the payee may be a prefix of the holder's name.
    holder_flat = "".join(holder_tokens)
    payee_flat = "".join(payee_tokens)
    if payee_flat and len(payee_flat) >= MIN_PREFIX_MATCH:
        if holder_flat.startswith(payee_flat) or payee_flat.startswith(holder_flat):
            return True, f"payee '{payee_norm}' matches account holder"

    matched = [t for t in distinctive if t in payee_tokens]
    if matched:
        return True, f"payee shares account-holder name '{matched[0]}'"

    vpa = extract_vpa(description) or counterparty_key.split("|")[0].replace(" ", "")
    if vpa:
        for token in distinctive:
            if len(token) >= 4 and token in vpa:
                return True, f"UPI handle '{vpa.lower()}' contains '{token}'"

    return False, ""


def annotate_self_transfer(subcategory: str) -> str:
    """Render a self-transfer label as `P2P Transfer Out (Self Transfer)`."""
    base = str(subcategory or "Transfer")
    if "(Self Transfer)" in base:
        return base
    return f"{base} (Self Transfer)"


# ============================================================
# Learned override registry
# ============================================================

class CounterpartyRegistry:
    """
    Human-supplied counterparty labels, persisted as JSON.

    Reloads when the file changes on disk so the web API and the pipeline stay in
    step within one process lifetime.

    Scope: an entry tied to an applicant beats a global one, so a name meaning
    different things for two applicants does not cross-contaminate.
    """

    _lock = threading.Lock()

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else REGISTRY_PATH
        self._entries: Dict[str, List[Dict[str, Any]]] = {}
        self._mtime: float = -1.0
        self.reload()

    # -- persistence -------------------------------------------------

    def reload(self, force: bool = False) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            if force or self._mtime != -1.0:
                self._entries = {}
                self._mtime = -1.0
            return

        if not force and mtime == self._mtime:
            return

        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            self._entries = raw.get("counterparties", {}) if isinstance(raw, dict) else {}
            self._mtime = mtime
            logger.info(
                f"Counterparty registry loaded: {len(self._entries)} counterparties "
                f"from {self.path}"
            )
        except Exception as exc:
            logger.warning(f"Could not read counterparty registry {self.path}: {exc}")
            self._entries = {}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "counterparties": self._entries,
            }
            tmp = self.path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)

    # -- lookup ------------------------------------------------------

    def lookup(self, key: str, applicant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Best matching entry: applicant-scoped first, then global."""
        if not key:
            return None
        self.reload()

        candidates: List[Dict[str, Any]] = []
        for stored_key, entries in self._entries.items():
            if keys_match(key, stored_key):
                candidates.extend(entries)
        if not candidates:
            return None

        if applicant_id:
            scoped = [e for e in candidates
                      if e.get("scope") == "applicant" and e.get("applicant_id") == applicant_id]
            if scoped:
                return sorted(scoped, key=lambda e: e.get("updated_at", ""))[-1]

        globals_ = [e for e in candidates if e.get("scope", "global") == "global"]
        if globals_:
            return sorted(globals_, key=lambda e: e.get("updated_at", ""))[-1]
        return None

    # -- mutation ----------------------------------------------------

    def set(self, key: str, *, category: str, subcategory: str,
            needs_wants: str = "Unknown", scope: str = "global",
            applicant_id: Optional[str] = None, source: str = "user",
            note: str = "") -> Dict[str, Any]:
        if not key:
            raise ValueError("counterparty key is required")
        if scope not in ("global", "applicant"):
            raise ValueError("scope must be 'global' or 'applicant'")
        if scope == "applicant" and not applicant_id:
            raise ValueError("applicant_id is required for applicant scope")

        self.reload()
        entry = {
            "category": category,
            "subcategory": subcategory,
            "needs_wants": needs_wants,
            "scope": scope,
            "applicant_id": applicant_id,
            "source": source,
            "note": note,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        entries = self._entries.setdefault(key, [])
        # Replace any entry with the same scope/applicant rather than stacking.
        entries[:] = [
            e for e in entries
            if not (e.get("scope") == scope and e.get("applicant_id") == applicant_id)
        ]
        entries.append(entry)
        self.save()
        logger.info(f"Counterparty override set: {key} -> {category}/{subcategory} ({scope})")
        return entry

    def delete(self, key: str, *, scope: str = "global",
               applicant_id: Optional[str] = None) -> bool:
        self.reload()
        entries = self._entries.get(key)
        if not entries:
            return False
        before = len(entries)
        entries[:] = [
            e for e in entries
            if not (e.get("scope") == scope and e.get("applicant_id") == applicant_id)
        ]
        if not entries:
            self._entries.pop(key, None)
        if len(entries) != before:
            self.save()
            return True
        return False

    def all_entries(self) -> Dict[str, List[Dict[str, Any]]]:
        self.reload()
        return dict(self._entries)


_registry: Optional[CounterpartyRegistry] = None


def get_registry(path: Optional[Path] = None) -> CounterpartyRegistry:
    """Process-wide registry singleton (reloads itself when the file changes)."""
    global _registry
    if _registry is None or path is not None:
        _registry = CounterpartyRegistry(path)
    return _registry

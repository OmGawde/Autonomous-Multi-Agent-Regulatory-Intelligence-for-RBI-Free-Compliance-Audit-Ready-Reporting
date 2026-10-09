"""Deterministic natural-language query resolver over the transaction ledger.

The Underwriting Copilot used to answer only five hardcoded topics (fintech
loans, balance drops, tax payments, large credits, scorecard metrics). Every
other question -- "which is the highest payment", "how much did I spend in
October", "how many EMIs are there" -- fell through to a generic deflection
telling the user to ask about one of those five topics instead. There was no
general question-answering capability to be blocked; there simply wasn't one.

This module supplies it, without an LLM. That is deliberate and matches the
architecture rule the project states for itself: deterministic code does the
arithmetic, the model is reserved for judgement. A language model asked to find
the largest debit among 358 rows will sometimes return a number that is not in
the statement at all, and on a credit file that is the one failure mode nobody
can afford.

Resolution is intent-driven: a question is only answered when a recognisable
intent (superlative, total, count, average, listing) is found, so that topic
questions still reach the specialised handlers that phrase answers better.
`strict=False` relaxes this for the final fallback, where a plain entity search
is more useful than a canned refusal.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- Intent vocabulary -----------------------------------------------------

_MAX_WORDS = {
    "highest", "largest", "biggest", "maximum", "max", "greatest",
    "costliest", "dearest", "priciest", "heaviest",
}
_MIN_WORDS = {
    "lowest", "smallest", "minimum", "min", "least", "cheapest", "tiniest",
}
_TOTAL_WORDS = {"total", "sum", "altogether", "overall", "aggregate", "combined", "totalled", "totaled"}
_AVG_WORDS = {"average", "mean", "typical", "avg"}
_COUNT_WORDS = {"many", "count", "number"}
_LIST_WORDS = {"list", "show", "display", "breakdown", "enumerate", "top"}

# --- Direction vocabulary --------------------------------------------------

_DEBIT_WORDS = {
    "payment", "payments", "paid", "pay", "pays", "spend", "spent", "spending",
    "debit", "debits", "debited", "outflow", "outflows", "withdrawal",
    "withdrawals", "withdrew", "expense", "expenses", "bill",
    "bills", "purchase", "purchases", "sent", "outgoing", "charge", "charges",
    "outgo", "expenditure", "spends",
}
# "emi" is deliberately NOT a direction word. Treating it as a generic synonym
# for "debit" made "how many EMIs are there" count every debit in the statement
# -- 320 of them -- instead of the loan instalments actually asked about. It is
# a subject, so it is left to match the narration and subcategory instead.
_CREDIT_WORDS = {
    "credit", "credits", "credited", "received", "receive", "receipt",
    "receipts", "inflow", "inflows", "deposit", "deposits", "deposited",
    "income", "salary", "salaries", "earned", "earning", "earnings",
    "incoming", "refund", "refunds", "reimbursement",
}
_BALANCE_WORDS = {"balance", "balances"}

# Words that name both a direction and a subject. "salary" says "a credit", but
# "average salary" means the salary credits, not every credit -- which is what
# it returned while these were treated as direction-only. They are promoted to
# filters only when they match a *classification* field, so the promotion
# cannot fire off an incidental narration like "CLIENT PAYMENT FOR ORDER".
# Kept deliberately narrow: "credit" is excluded, or "total credits" would
# quietly collapse to the Credit Card subcategory.
_SUBJECT_OVERRIDES = {"salary", "salaries", "income", "refund", "refunds"}

# "What is X?" / "Who is X?" / "Tell me about X" -- an identity question about a
# counterparty, not an arithmetic one. Returning a bare transaction dump for
# these is what made the Copilot feel evasive: the analyst asked what something
# *is* and got a list of what it *cost*.
_PROFILE_PATTERNS = (
    "what is", "what's", "whats", "what are", "who is", "who's", "whos",
    "who are", "tell me about", "tell me more about", "describe", "explain",
    "what does", "what kind of", "what sort of",
)

# Payment rails, as they appear at the head of an Indian bank narration.
_RAILS = {
    "upi": "UPI", "neft": "NEFT", "imps": "IMPS", "rtgs": "RTGS",
    "ach": "ACH mandate", "nach": "NACH mandate", "ecs": "ECS mandate",
    "clg": "cheque clearing", "chq": "cheque", "bil": "online bill payment",
    "atm": "ATM", "pos": "card (POS)", "inf": "internal transfer",
}

_ENTITY_SUFFIXES = (
    ("pvt ltd", "a private limited company"),
    ("private limited", "a private limited company"),
    ("llp", "a limited liability partnership"),
    ("ltd", "a limited company"),
    ("limited", "a limited company"),
)

_IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

# Words that must never be treated as a merchant/counterparty to search for.
# "payment" in particular appears inside real narrations ("CLIENT PAYMENT FOR
# ORDER"), so leaving it in would silently filter the ledger down to unrelated
# rows while looking like it worked.
_STOPWORDS = (
    _MAX_WORDS | _MIN_WORDS | _TOTAL_WORDS | _AVG_WORDS | _COUNT_WORDS
    | _LIST_WORDS | _DEBIT_WORDS | _CREDIT_WORDS | _BALANCE_WORDS
    | set(_MONTHS)
    | {
        "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
        "the", "this", "that", "these", "those", "there", "here", "and", "but",
        "for", "from", "with", "without", "into", "onto", "about", "over",
        "under", "between", "during", "within", "across", "per", "was", "were",
        "is", "are", "am", "been", "being", "be", "has", "have", "had", "did",
        "does", "do", "done", "will", "would", "shall", "should", "can",
        "could", "may", "might", "must", "any", "all", "some", "each", "every",
        "none", "not", "his", "her", "its", "their", "our", "your", "my",
        "mine", "me", "you", "they", "them", "we", "us", "it", "he", "she",
        "borrower", "applicant", "customer", "client", "account", "statement",
        "statements", "transaction", "transactions", "txn", "txns", "ledger",
        "entry", "entries", "row", "rows", "record", "records", "amount",
        "amounts", "value", "values", "money", "rupees", "rupee", "inr",
        "much", "most", "more", "less", "than", "then", "also", "please",
        "tell", "give", "find", "get", "want", "need", "know", "see", "look",
        "month", "months", "monthly", "year", "years", "yearly", "day", "days",
        "daily", "week", "weeks", "weekly", "date", "dates", "period",
        "made", "make", "name", "names", "type", "types", "kind", "detail",
        "details", "information", "info", "data", "summary", "overall",
    }
)


def _fmt_money(value: float) -> str:
    return f"₹{value:,.2f}"


def _token_matches(token: str, haystack: str) -> bool:
    """Does `token` occur in `haystack` as a real reference?

    Short tokens must match on a word boundary; long ones may match anywhere.
    Bank narrations run words together ("UPI/SWIGGYSTORES"), so a plain
    substring test is what makes "swiggy" findable at all -- but applied to
    short tokens it matches nonsense: "emi" inside PREMIUM and REMITTANCE,
    "top" inside LAPTOP. Four characters is where the two behaviours trade off.
    """
    if len(token) <= 4:
        return re.search(rf"\b{re.escape(token)}\b", haystack) is not None
    return token in haystack


def _resolve_token(token: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    """Return the form of `token` that occurs in the ledger, if any.

    Falls back to the singular so "how many EMIs" finds rows narrating "EMI".
    """
    for candidate in (token, token[:-1] if token.endswith("s") and len(token) > 3 else None):
        if not candidate:
            continue
        if any(_token_matches(candidate, row["haystack"]) for row in rows):
            return candidate
    return None


def _parse_date(value: Any) -> Optional[datetime]:
    """Best-effort date parse; the ledger carries several representations."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _as_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("₹", "").strip() or 0.0)
    except ValueError:
        return 0.0


def _normalise(txns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten the ledger into one shape, whatever the caller handed over."""
    rows = []
    for txn in txns or []:
        narration = str(txn.get("narration") or txn.get("description") or "").strip()
        debit = _as_float(txn.get("debit"))
        credit = _as_float(txn.get("credit"))
        if debit == 0.0 and credit == 0.0:
            # Some sources carry a single signed `amount` instead.
            amount = _as_float(txn.get("amount"))
            if amount < 0:
                debit = abs(amount)
            elif amount > 0:
                credit = amount

        # Classification is merged onto the rows by the API, so category and
        # counterparty are searchable alongside the raw narration.
        haystack = " ".join(
            str(txn.get(k) or "")
            for k in ("narration", "description", "category", "subcategory",
                      "counterparty_key", "recurrence_type")
        ).lower()

        rows.append({
            "date": str(txn.get("date") or ""),
            "date_obj": _parse_date(txn.get("date")),
            "narration": narration,
            "debit": debit,
            "credit": credit,
            "balance": _as_float(txn.get("balance")),
            "category": str(txn.get("category") or ""),
            "subcategory": str(txn.get("subcategory") or ""),
            "class_text": f"{txn.get('category') or ''} {txn.get('subcategory') or ''}".lower(),
            "haystack": haystack,
        })
    return rows


def _cite(row: Dict[str, Any], amount: Optional[float] = None) -> Dict[str, Any]:
    if amount is None:
        amount = row["debit"] if row["debit"] > 0 else row["credit"]
    return {"date": row["date"], "narration": row["narration"], "amount": amount}


def _ref(row: Dict[str, Any], amount: Optional[float] = None) -> str:
    if amount is None:
        amount = row["debit"] if row["debit"] > 0 else row["credit"]
    return f"[Ref: {row['date']} | {row['narration']} | {_fmt_money(amount)}]"


class _Query:
    """What a question is asking for, once parsed."""

    def __init__(self, question: str, rows: List[Dict[str, Any]]):
        self.raw = question
        self.lower = question.lower()
        self.tokens = re.findall(r"[a-z0-9']+", self.lower)
        self.token_set = set(self.tokens)
        self.rows = rows

        self.wants_max = bool(self.token_set & _MAX_WORDS) or "top" in self.token_set
        self.wants_min = bool(self.token_set & _MIN_WORDS)
        # "how much ...?" is the commonest way to ask for a total and carries
        # none of the words in _TOTAL_WORDS. Without this, "how much did I
        # spend in October" had no intent at all and fell through to the
        # balance-drop handler, which happens to key on the word "october".
        self.wants_total = bool(self.token_set & _TOTAL_WORDS) or "how much" in self.lower
        self.wants_avg = bool(self.token_set & _AVG_WORDS)
        self.wants_count = bool(self.token_set & _COUNT_WORDS) and (
            "how many" in self.lower or "number of" in self.lower or "count" in self.token_set
        )
        self.wants_list = bool(self.token_set & _LIST_WORDS) or "top" in self.token_set
        self.about_balance = bool(self.token_set & _BALANCE_WORDS)
        self.wants_profile = any(p in self.lower for p in _PROFILE_PATTERNS)
        self.by_month = "month" in self.token_set or "monthly" in self.token_set

        debit_hit = bool(self.token_set & _DEBIT_WORDS)
        credit_hit = bool(self.token_set & _CREDIT_WORDS)
        if debit_hit and not credit_hit:
            self.direction = "debit"
        elif credit_hit and not debit_hit:
            self.direction = "credit"
        else:
            self.direction = None

        self.top_n = self._parse_top_n()
        self.months = self._parse_months()
        self.years = {int(t) for t in self.tokens if re.fullmatch(r"20\d{2}", t)}
        self.entities = self._parse_entities()

    @property
    def has_intent(self) -> bool:
        return any([
            self.wants_max, self.wants_min, self.wants_total,
            self.wants_avg, self.wants_count, self.wants_list,
            self.wants_profile,
        ])

    @property
    def wants_arithmetic(self) -> bool:
        return any([
            self.wants_max, self.wants_min, self.wants_total,
            self.wants_avg, self.wants_count,
        ])

    def _parse_top_n(self) -> int:
        match = re.search(r"\btop\s+(\d{1,2})\b", self.lower)
        if match:
            return max(1, min(25, int(match.group(1))))
        return 5

    def _parse_months(self) -> set:
        return {_MONTHS[t] for t in self.tokens if t in _MONTHS}

    def _parse_entities(self) -> List[str]:
        """Content words from the question that actually occur in the ledger.

        Matching against the ledger rather than a fixed merchant list is what
        lets an unanticipated name work: if the word is in the statement, it is
        a usable filter; if it is not, it is just prose.
        """
        candidates = [
            t for t in self.tokens
            if len(t) >= 3 and t not in _STOPWORDS and not t.isdigit()
        ]
        found = []
        for token in candidates:
            resolved = _resolve_token(token, self.rows)
            if resolved and resolved not in found:
                found.append(resolved)

        # Dual-purpose words, matched against the classification only.
        for token in self.tokens:
            if token not in _SUBJECT_OVERRIDES:
                continue
            for form in (token, token[:-1] if token.endswith("s") else None):
                if not form:
                    continue
                if any(_token_matches(form, r["class_text"]) for r in self.rows):
                    if form not in found:
                        found.append(form)
                    break
        return found

    def filtered(self) -> List[Dict[str, Any]]:
        rows = self.rows
        if self.direction == "debit":
            rows = [r for r in rows if r["debit"] > 0]
        elif self.direction == "credit":
            rows = [r for r in rows if r["credit"] > 0]
        if self.months:
            rows = [r for r in rows if r["date_obj"] and r["date_obj"].month in self.months]
        if self.years:
            rows = [r for r in rows if r["date_obj"] and r["date_obj"].year in self.years]
        if self.entities:
            rows = [
                r for r in rows
                if all(_token_matches(e, r["haystack"]) for e in self.entities)
            ]
        return rows

    def amount_of(self, row: Dict[str, Any]) -> float:
        if self.direction == "debit":
            return row["debit"]
        if self.direction == "credit":
            return row["credit"]
        return row["debit"] if row["debit"] > 0 else row["credit"]

    def scope_label(self) -> str:
        bits = []
        if self.direction == "debit":
            bits.append("payment")
        elif self.direction == "credit":
            bits.append("credit")
        else:
            bits.append("transaction")
        return " ".join(bits)

    def scope_suffix(self) -> str:
        bits = []
        if self.entities:
            bits.append("matching " + ", ".join(f"'{e}'" for e in self.entities))
        if self.months:
            names = [datetime(2000, m, 1).strftime("%B") for m in sorted(self.months)]
            bits.append("in " + ", ".join(names))
        if self.years:
            bits.append("in " + ", ".join(str(y) for y in sorted(self.years)))
        return (" " + " ".join(bits)) if bits else ""


def _answer_balance(q: _Query) -> Optional[Dict[str, Any]]:
    rows = [r for r in q.filtered() if r["balance"] != 0.0]
    if not rows:
        return None
    if q.wants_max:
        row = max(rows, key=lambda r: r["balance"])
        label = "highest"
    elif q.wants_min:
        row = min(rows, key=lambda r: r["balance"])
        label = "lowest"
    else:
        return None
    return {
        "answer": (
            f"The {label} running balance{q.scope_suffix()} was "
            f"{_fmt_money(row['balance'])} on {row['date']}, after: "
            f"{row['narration']}. {_ref(row, row['balance'])}"
        ),
        "citations": [_cite(row, row["balance"])],
    }


def _describe_rails(rows: List[Dict[str, Any]]) -> List[str]:
    """Which payment rails this counterparty was reached through."""
    seen: Dict[str, int] = {}
    for row in rows:
        upper = row["narration"].upper()
        for key, label in _RAILS.items():
            if re.search(rf"\b{key.upper()}\b", upper):
                seen[label] = seen.get(label, 0) + 1
                break
    return [f"{label} ({count})" for label, count in
            sorted(seen.items(), key=lambda kv: -kv[1])]


def _legal_form(rows: List[Dict[str, Any]]) -> Optional[str]:
    blob = " ".join(r["narration"].lower() for r in rows)
    for needle, label in _ENTITY_SUFFIXES:
        if re.search(rf"\b{re.escape(needle)}\b", blob):
            return label
    return None


def _answer_profile(q: _Query) -> Optional[Dict[str, Any]]:
    """Describe a counterparty from everything the ledger records about it.

    The statement can say how much moved, when, over which rail, and how the
    pipeline classified it. It cannot say what the business does -- that is not
    written anywhere in a bank statement, and guessing it is precisely the
    fabrication the citation guardrail exists to prevent. So the answer states
    what is recorded, and is explicit about where the record stops.
    """
    rows = q.filtered()
    if not rows:
        return None

    subject = " ".join(e.title() for e in q.entities) or "That counterparty"
    debits = [r for r in rows if r["debit"] > 0]
    credits = [r for r in rows if r["credit"] > 0]
    total_debit = sum(r["debit"] for r in debits)
    total_credit = sum(r["credit"] for r in credits)

    dated = sorted([r["date_obj"] for r in rows if r["date_obj"]])
    span = ""
    if len(dated) >= 2:
        span = f" between {dated[0].date()} and {dated[-1].date()}"
    elif dated:
        span = f" on {dated[0].date()}"

    parts = []

    # Flow direction and size.
    if debits and not credits:
        parts.append(
            f"{subject} appears in {len(rows)} outgoing payment(s){span}, "
            f"totalling {_fmt_money(total_debit)}."
        )
    elif credits and not debits:
        parts.append(
            f"{subject} appears in {len(rows)} incoming credit(s){span}, "
            f"totalling {_fmt_money(total_credit)}."
        )
    else:
        parts.append(
            f"{subject} appears in {len(rows)} transaction(s){span}: "
            f"{len(debits)} paid out ({_fmt_money(total_debit)}) and "
            f"{len(credits)} received ({_fmt_money(total_credit)})."
        )

    # Legal form, where the narration spells it out.
    form = _legal_form(rows)
    if form:
        parts.append(f"The narration identifies it as {form}.")

    # How the money moved.
    rails = _describe_rails(rows)
    if rails:
        parts.append("Paid via " + ", ".join(rails) + ".")

    # Fixed obligation vs variable trade payment -- the distinction an
    # underwriter cares about most.
    amounts = [q.amount_of(r) for r in rows]
    if len(amounts) >= 2:
        if len(set(amounts)) == 1:
            parts.append(
                f"Every instalment is identical at {_fmt_money(amounts[0])}, "
                f"consistent with a fixed recurring obligation."
            )
        else:
            parts.append(
                f"Amounts vary from {_fmt_money(min(amounts))} to "
                f"{_fmt_money(max(amounts))}, so this is not a fixed instalment."
            )

    # What the pipeline already decided about it.
    labels = {}
    for row in rows:
        if row["category"]:
            key = f"{row['category']} / {row['subcategory']}" if row["subcategory"] else row["category"]
            labels[key] = labels.get(key, 0) + 1
    if labels:
        best = max(labels, key=lambda k: labels[k])
        parts.append(f"Classified as {best}.")

    # Counterparty bank coordinates, when the narration carries them.
    #
    # Direction decides whose bank this is: on an outgoing NEFT the IFSC
    # belongs to the payee, on an incoming one it belongs to the remitter.
    # Labelling it "beneficiary" regardless inverts the two parties on every
    # credit. Only some rows carry one (ACH legs usually do not), so the count
    # is stated rather than implying it applies to all of them.
    ifsc_rows = {}
    for row in rows:
        found = _IFSC_RE.search(row["narration"].upper())
        if found:
            ifsc_rows.setdefault(found.group(1), []).append(row)
    if ifsc_rows:
        codes = sorted(ifsc_rows, key=lambda c: -len(ifsc_rows[c]))
        code = codes[0]
        matched = ifsc_rows[code]
        carrying = sum(1 for rs in ifsc_rows.values() for _ in rs)
        if all(r["credit"] > 0 for r in matched):
            whose = f"Funds arrived from an account at IFSC {code}"
        elif all(r["debit"] > 0 for r in matched):
            whose = f"Paid to an account at IFSC {code}"
        else:
            whose = f"IFSC {code} appears on the transfer leg"
        scope = f" (on {len(matched)} of {len(rows)} transactions)" if carrying < len(rows) else ""
        extra = f"; also {', '.join(codes[1:])}" if len(codes) > 1 else ""
        parts.append(f"{whose}{scope}{extra}.")

    # The boundary of what a statement can answer.
    parts.append(
        "The statement records these payments but not the nature of the "
        "business itself, which is not written in the ledger."
    )

    ordered = sorted(rows, key=q.amount_of, reverse=True)[:5]
    parts.append("Evidence: " + "; ".join(_ref(r, q.amount_of(r)) for r in ordered) + ".")

    return {
        "answer": " ".join(parts),
        "citations": [_cite(r, q.amount_of(r)) for r in ordered],
    }


def _answer_by_month(q: _Query) -> Optional[Dict[str, Any]]:
    rows = q.filtered()
    if not rows:
        return None
    buckets: Dict[str, float] = {}
    for row in rows:
        if not row["date_obj"]:
            continue
        key = row["date_obj"].strftime("%Y-%m")
        buckets[key] = buckets.get(key, 0.0) + q.amount_of(row)
    if not buckets:
        return None

    if q.wants_max:
        key = max(buckets, key=lambda k: buckets[k])
        label = "highest"
    elif q.wants_min:
        key = min(buckets, key=lambda k: buckets[k])
        label = "lowest"
    else:
        ordered = sorted(buckets.items())
        listing = "; ".join(f"{k}: {_fmt_money(v)}" for k, v in ordered)
        return {
            "answer": f"{q.scope_label().title()} totals by month{q.scope_suffix()} — {listing}.",
            "citations": [],
        }

    month_rows = [r for r in rows if r["date_obj"] and r["date_obj"].strftime("%Y-%m") == key]
    month_rows.sort(key=q.amount_of, reverse=True)
    top = month_rows[:3]
    return {
        "answer": (
            f"{key} was the {label} month for {q.scope_label()}s{q.scope_suffix()}, "
            f"totalling {_fmt_money(buckets[key])} across {len(month_rows)} transaction(s). "
            f"Largest contributors: " + "; ".join(_ref(r, q.amount_of(r)) for r in top) + "."
        ),
        "citations": [_cite(r, q.amount_of(r)) for r in top],
    }


def resolve(
    question: str,
    txns: List[Dict[str, Any]],
    strict: bool = True,
) -> Optional[Dict[str, Any]]:
    """Answer `question` from the ledger, or return None if it cannot.

    Args:
        question: the analyst's question, as typed.
        txns: transaction rows, with classification merged on where available.
        strict: when True, answer only questions carrying an explicit intent
            (superlative / total / count / average / listing), leaving topic
            questions to the specialised handlers. When False, a bare entity
            mention is enough -- used for the final fallback, where a real
            search beats a canned refusal.
    """
    rows = _normalise(txns)
    if not rows:
        return None

    q = _Query(question, rows)

    if strict and not q.has_intent:
        return None
    if not strict and not q.has_intent and not q.entities:
        return None

    # Balance is a stock, not a flow: it is read off the row, never summed.
    if q.about_balance and (q.wants_max or q.wants_min):
        result = _answer_balance(q)
        if result:
            return result

    if q.by_month and (q.wants_max or q.wants_min or q.wants_total or q.wants_list):
        result = _answer_by_month(q)
        if result:
            return result

    # "What is X?" -- an identity question. Only when the analyst is not also
    # asking for a number, so "what is the largest payment" stays arithmetic.
    if q.wants_profile and q.entities and not q.wants_arithmetic:
        result = _answer_profile(q)
        if result:
            return result

    selected = q.filtered()
    if not selected:
        scope = q.scope_suffix().strip() or "matching that description"
        return {
            "answer": (
                f"No {q.scope_label()}s {scope} appear in this statement. "
                f"The ledger holds {len(rows)} transactions in total."
            ),
            "citations": [],
        }

    amounts = [q.amount_of(r) for r in selected]
    total = sum(amounts)

    if q.wants_count:
        return {
            "answer": (
                f"There are {len(selected)} {q.scope_label()}(s){q.scope_suffix()}, "
                f"totalling {_fmt_money(total)}."
            ),
            "citations": [_cite(r, q.amount_of(r)) for r in
                          sorted(selected, key=q.amount_of, reverse=True)[:5]],
        }

    if q.wants_avg:
        avg = total / len(selected) if selected else 0.0
        return {
            "answer": (
                f"The average {q.scope_label()}{q.scope_suffix()} is {_fmt_money(avg)}, "
                f"across {len(selected)} transaction(s) totalling {_fmt_money(total)}."
            ),
            "citations": [],
        }

    if q.wants_total and not (q.wants_max or q.wants_min):
        ordered = sorted(selected, key=q.amount_of, reverse=True)[:5]
        return {
            "answer": (
                f"Total {q.scope_label()}s{q.scope_suffix()}: {_fmt_money(total)} "
                f"across {len(selected)} transaction(s). Largest: "
                + "; ".join(_ref(r, q.amount_of(r)) for r in ordered) + "."
            ),
            "citations": [_cite(r, q.amount_of(r)) for r in ordered],
        }

    if q.wants_max or q.wants_min:
        reverse = bool(q.wants_max)
        ordered = sorted(selected, key=q.amount_of, reverse=reverse)
        best = ordered[0]
        label = "largest" if reverse else "smallest"

        if q.wants_list and len(ordered) > 1:
            picked = ordered[:q.top_n]
            return {
                "answer": (
                    f"The {len(picked)} {label} {q.scope_label()}s{q.scope_suffix()}: "
                    + "; ".join(_ref(r, q.amount_of(r)) for r in picked) + "."
                ),
                "citations": [_cite(r, q.amount_of(r)) for r in picked],
            }

        runners = ordered[1:4]
        answer = (
            f"The {label} {q.scope_label()}{q.scope_suffix()} is "
            f"{_fmt_money(q.amount_of(best))} on {best['date']} — {best['narration']}. "
            f"{_ref(best, q.amount_of(best))}"
        )
        if best["category"]:
            answer += f" Categorised as {best['category']}"
            if best["subcategory"]:
                answer += f" / {best['subcategory']}"
            answer += "."
        if runners:
            answer += (
                " Next: " + "; ".join(_ref(r, q.amount_of(r)) for r in runners) + "."
            )
        return {
            "answer": answer,
            "citations": [_cite(r, q.amount_of(r)) for r in ordered[:4]],
        }

    if q.wants_list or q.entities:
        ordered = sorted(selected, key=q.amount_of, reverse=True)[:q.top_n]
        return {
            "answer": (
                f"Found {len(selected)} {q.scope_label()}(s){q.scope_suffix()}, "
                f"totalling {_fmt_money(total)}. Showing the {len(ordered)} largest: "
                + "; ".join(_ref(r, q.amount_of(r)) for r in ordered) + "."
            ),
            "citations": [_cite(r, q.amount_of(r)) for r in ordered],
        }

    return None


def select_context(
    question: str,
    txns: List[Dict[str, Any]],
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Pick the rows most relevant to `question`, for a model's prompt.

    FinanceParam has a 2048-token context, so a 358-row ledger cannot be handed
    over wholesale -- and truncating it arbitrarily would let the model answer
    about whichever rows happened to survive. Rows the question actually names
    are preferred; the largest transactions stand in when it names none, since
    those are what an underwriter would look at first.
    """
    rows = _normalise(txns)
    if not rows:
        return []

    q = _Query(question, rows)
    selected = q.filtered() if (q.entities or q.direction or q.months or q.years) else []
    if not selected:
        selected = rows

    selected = sorted(selected, key=q.amount_of, reverse=True)[:limit]
    return [
        {
            "date": r["date"],
            "narration": r["narration"],
            "debit": r["debit"],
            "credit": r["credit"],
            "category": r["category"],
            "subcategory": r["subcategory"],
        }
        for r in selected
    ]


def capability_summary(txns: List[Dict[str, Any]]) -> str:
    """What the ledger holds, for when a question could not be resolved."""
    rows = _normalise(txns)
    if not rows:
        return "No transactions are loaded for this application."
    debits = [r for r in rows if r["debit"] > 0]
    credits = [r for r in rows if r["credit"] > 0]
    dated = [r["date_obj"] for r in rows if r["date_obj"]]
    period = ""
    if dated:
        period = f" covering {min(dated).date()} to {max(dated).date()}"
    return (
        f"This statement holds {len(rows)} transactions{period}: "
        f"{len(debits)} debits totalling {_fmt_money(sum(r['debit'] for r in debits))} and "
        f"{len(credits)} credits totalling {_fmt_money(sum(r['credit'] for r in credits))}."
    )

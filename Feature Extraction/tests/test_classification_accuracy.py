"""
Classification accuracy against a hand-labelled set of real narrations.

The bundled reports carry a "Classification Accuracy" line that is really a
*coverage* number -- the share of rows a rule fired on, regardless of whether
the answer was right. Nothing compared output to ground truth. This does.

`tests/data/labelled_transactions.csv` holds real narrations drawn from the
Axis, SBI and ICICI statements plus a GENERIC set, labelled with the category
each should resolve to. It deliberately over-samples the failure modes that
were found in the field (substring collisions, direction errors, rail formats).

The thresholds below are ratchets: raise them when accuracy improves, never
lower them to make a run pass.
"""

from pathlib import Path

import pandas as pd
import pytest

from src.classifier import TransactionClassifier

LABELLED = Path(__file__).parent / "data" / "labelled_transactions.csv"

# Ratchet. Measured accuracy on this set is currently 100%; the thresholds sit
# just below so a genuine regression fails the build while an unrelated
# dictionary tweak does not.
MIN_CATEGORY_ACCURACY = 0.95
MAX_UNCATEGORIZED_RATE = 0.05

JUNK_SUBCATS = {"Other Expense", "Other Income", "Unknown", "Other", "Uncategorized"}


@pytest.fixture(scope="module")
def labelled():
    assert LABELLED.exists(), f"missing labelled set: {LABELLED}"
    return pd.read_csv(LABELLED)


@pytest.fixture(scope="module", autouse=True)
def isolated_registry(tmp_path_factory):
    """
    Point the counterparty registry at an empty temporary file.

    These tests measure the *rules*. Without isolation they would also measure
    whatever counterparties happen to be tagged on the developer's machine, so a
    user teaching the system one label could turn this suite red.
    """
    from src.rules import counterparty

    path = tmp_path_factory.mktemp("registry") / "counterparty_overrides.json"
    original = counterparty._registry
    counterparty.get_registry(path)
    yield
    counterparty._registry = original


@pytest.fixture(scope="module")
def predictions(labelled, isolated_registry):
    clf = TransactionClassifier()
    rows = []
    for _, r in labelled.iterrows():
        bank = r["bank"] if r["bank"] != "GENERIC" else "Other"
        df = pd.DataFrame([{
            "date": pd.Timestamp("2025-06-15"),
            "description": r["description"],
            "debit": float(r["debit"]),
            "credit": float(r["credit"]),
            "balance": 100000.0,
            "year_month": "2025-06",
        }])
        out = clf.classify_dataframe(df, bank)
        rows.append({
            "bank": r["bank"],
            "description": r["description"],
            "expected": r["expected_category"],
            "actual": out.iloc[0]["category"],
            "subcategory": out.iloc[0]["subcategory"],
            "method": out.iloc[0]["classification_method"],
            "expected_direction": r["expected_direction"],
            "actual_direction": out.iloc[0]["transaction_type"],
            "expected_needs_wants": r.get("expected_needs_wants", ""),
            "actual_needs_wants": out.iloc[0]["needs_wants"],
            "note": r["note"],
        })
    return pd.DataFrame(rows)


def test_needs_wants_accuracy(predictions):
    """
    Needs/wants must be evidence-based.

    Merchant payments were previously labelled "Want" unconditionally, which
    booked oil, milk, medicine and bus fares as discretionary and inflated one
    statement's Wants figure by 3-5x.
    """
    labelled = predictions[predictions["expected_needs_wants"] != ""]
    assert not labelled.empty
    correct = labelled["expected_needs_wants"] == labelled["actual_needs_wants"]
    accuracy = correct.mean()
    if accuracy < 0.90:
        wrong = labelled[~correct][
            ["description", "expected_needs_wants", "actual_needs_wants", "note"]]
        pytest.fail(
            f"needs/wants accuracy {accuracy:.1%} below 90%\n"
            + wrong.to_string(max_colwidth=52)
        )


def test_no_expense_row_lacks_needs_wants(predictions):
    """Every expense must be Need, Want or an explicit Unknown -- never blank."""
    expenses = predictions[predictions["actual"] == "Expense"]
    bad = expenses[~expenses["actual_needs_wants"].isin(["Need", "Want", "Unknown"])]
    assert bad.empty, (
        "expense rows with a blank or N/A needs_wants:\n"
        + bad[["description", "subcategory", "actual_needs_wants"]].to_string(max_colwidth=52)
    )


def test_non_expense_rows_are_marked_not_applicable(predictions):
    """Needs/wants is meaningless for transfers, income and investments."""
    non_expense = predictions[predictions["actual"].isin(
        ["Income", "Investment", "Transfer", "Banking"])]
    bad = non_expense[non_expense["actual_needs_wants"] != "Not Applicable"]
    assert bad.empty, (
        "non-expense rows carrying a needs/wants value:\n"
        + bad[["description", "actual", "actual_needs_wants"]].to_string(max_colwidth=52)
    )


def test_category_accuracy_meets_threshold(predictions):
    correct = (predictions["expected"] == predictions["actual"])
    accuracy = correct.mean()

    if accuracy < MIN_CATEGORY_ACCURACY:
        wrong = predictions[~correct][["description", "expected", "actual", "note"]]
        pytest.fail(
            f"category accuracy {accuracy:.1%} below {MIN_CATEGORY_ACCURACY:.0%}\n"
            + wrong.to_string(max_colwidth=60)
        )


def test_uncategorized_rate_within_threshold(predictions):
    rate = predictions["subcategory"].isin(JUNK_SUBCATS).mean()
    assert rate <= MAX_UNCATEGORIZED_RATE, (
        f"{rate:.1%} of labelled narrations landed in a catch-all subcategory "
        f"(limit {MAX_UNCATEGORIZED_RATE:.0%})"
    )


def test_direction_is_never_contradicted(predictions):
    """
    A credit must never be classified as an Expense, nor a debit as Income.

    This is what booked 13 monthly salary credits (Rs 6,55,838) as
    "Expense / Society / Property Tax" while the income engine counted the same
    money as income.
    """
    credits = predictions[predictions["expected_direction"] == "Credit"]
    bad_credits = credits[credits["actual"] == "Expense"]
    assert bad_credits.empty, (
        "credits classified as Expense:\n"
        + bad_credits[["description", "actual", "note"]].to_string(max_colwidth=60)
    )

    debits = predictions[predictions["expected_direction"] == "Debit"]
    bad_debits = debits[debits["actual"] == "Income"]
    assert bad_debits.empty, (
        "debits classified as Income:\n"
        + bad_debits[["description", "actual", "note"]].to_string(max_colwidth=60)
    )


def test_no_substring_collisions(predictions):
    """The specific false positives found on real statements stay fixed."""
    forbidden = {
        "garlic": "Insurance",
        "HOSPITALITY": "Healthcare",
        "Bandhan": "Dhan",
        "Cable": "Taxi",
    }
    for token, wrong_subcat in forbidden.items():
        rows = predictions[predictions["description"].str.contains(token, case=False, na=False)]
        for _, r in rows.iterrows():
            assert wrong_subcat.lower() not in str(r["subcategory"]).lower(), (
                f"{token!r} still resolves to {r['subcategory']!r}: {r['description']}"
            )


def test_salary_credits_are_income(predictions):
    salary_rows = predictions[predictions["note"].str.contains("salary", case=False, na=False)]
    assert not salary_rows.empty
    assert (salary_rows["actual"] == "Income").all(), (
        "salary credits not classified as Income:\n"
        + salary_rows[salary_rows["actual"] != "Income"][
            ["description", "actual", "note"]].to_string(max_colwidth=60)
    )


def test_report_accuracy_summary(predictions, capsys):
    """Not an assertion -- prints the per-bank breakdown for visibility."""
    predictions["correct"] = predictions["expected"] == predictions["actual"]
    summary = predictions.groupby("bank").agg(
        n=("correct", "size"),
        accuracy=("correct", "mean"),
    )
    overall = predictions["correct"].mean()
    with capsys.disabled():
        print("\n\nClassification accuracy vs labelled set")
        print(summary.to_string(float_format=lambda v: f"{v:.1%}"))
        print(f"{'OVERALL':<10} n={len(predictions):<4} accuracy={overall:.1%}")

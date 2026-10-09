"""
Parsing a narration by the tokens in it rather than by a per-bank slot layout.

The six hand-written parsers only recognise prefixes someone thought to write
down. HDFC, Kotak and every unrecognised bank had no parser at all, so they got
no rail, no payee and no VPA -- which meant Tier 1 was a complete no-op for
them and their transactions fell straight through to the model.

Rail tokens are national standards (NPCI defines UPI/IMPS/NACH, RBI defines
NEFT/RTGS, Finacle emits CWDR/EBA wherever it runs), which is why this
generalises to a bank nobody has written rules for, and a merchant dictionary
does not.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.rules.bank_rules import (  # noqa: E402
    get_description_parser,
    token_parse_description,
)


@pytest.mark.parametrize("narration,rail,payee", [
    ("UPI/P2M/349488479088/Chalo/ICICI Ban/PayviaRa", "UPI", "Chalo"),
    ("UPI-SWIGGY-swiggy@ybl-HDFC0000123-4512-Food order", "UPI", "SWIGGY"),
    ("ACH/VIDYALANKAR INSTITUT/VIDYAINSTTECH 16 049", "ACH", "VIDYALANKAR INSTITUT"),
    ("UPIAB/770912345678/DR/RAKESH KUMAR/UBIN0557137/rakesh@okaxis", "UPI", "RAKESH KUMAR"),
    ("CWDR//4521/MUMBAI-ANDHERI", "ATM", "MUMBAI-ANDHERI"),
    ("NEFT-HDFCH006229-ACME TRADERS PVT LTD-0001-HDFC0000240", "NEFT", "ACME TRADERS PVT LTD"),
])
def test_rail_and_payee_are_found_regardless_of_layout(narration, rail, payee):
    result = token_parse_description(narration)
    assert result["rail"] == rail
    assert result["payee"] == payee


def test_delimiters_vary_by_bank_and_are_detected():
    """`/`, `-`, `*` and `:` all appear across Indian banks."""
    slash = token_parse_description("UPI/P2A/123456789012/RAMESH KUMAR/SBIN0001/rk@oksbi")
    hyphen = token_parse_description("UPI-RAMESH KUMAR-rk@oksbi-SBIN0001-123456789012")
    assert slash["payee"] == hyphen["payee"] == "RAMESH KUMAR"
    assert slash["vpa"] == hyphen["vpa"] == "rk@oksbi"


def test_vpa_is_matched_within_a_field_not_across_the_narration():
    """
    A VPA local part may contain a hyphen, so searching a hyphen-delimited
    narration whole swallows everything to the left of the handle.
    """
    result = token_parse_description("UPI-SWIGGY-swiggy@ybl-HDFC0000123-4512-Food order")
    assert result["vpa"] == "swiggy@ybl"


def test_payee_is_the_first_name_like_field_not_the_longest():
    """The counterparty precedes the free-text remark in Indian narrations."""
    result = token_parse_description("UPI-SWIGGY-swiggy@ybl-HDFC0000123-4512-Food order")
    assert result["payee"] == "SWIGGY"
    assert result["remarks"] == "Food order"


def test_rail_prefixes_are_never_mistaken_for_a_payee():
    for narration in ("UPIAB/7709/DR/x/UBIN0557137", "MMT/IMPS/123/ /HDFC"):
        assert token_parse_description(narration)["payee"] not in ("UPIAB", "IMPS", "MMT", "UPI")


def test_counterparty_bank_is_not_taken_as_the_payee():
    result = token_parse_description("UPI/P2A/123456789012/PRIYA SHARMA/Union Ban/rent")
    assert result["payee"] == "PRIYA SHARMA"


def test_terse_finacle_narration_is_its_own_merchant_token():
    for narration in ("ICICI BANK CC", "DHFL", "LIC PREMIUM"):
        assert token_parse_description(narration)["payee"] == narration


def test_longest_rail_token_wins():
    """'CASH WDL' must beat 'CASH', 'UPIAB' must resolve as UPI."""
    assert token_parse_description("ATM/CASH WDL/1234")["rail"] == "ATM"
    assert token_parse_description("UPIAB/7709/CR/x")["rail"] == "UPI"


def test_unknown_bank_now_gets_a_real_parser():
    """
    HDFC, Kotak, 'Other' and any calibrated bank previously received a stub that
    set a rail and nothing else.
    """
    for bank in ("HDFC", "Kotak", "Other", "Canara Bank", "Auto-Detect"):
        parser = get_description_parser(bank)
        result = parser("UPI/P2M/349488479088/Chalo/ICICI Ban/PayviaRa")
        assert result["rail"] == "UPI"
        assert result["payee"], f"{bank} still gets no payee"


def test_a_bank_specific_parser_is_not_overridden_by_the_fallback():
    """
    The hand-written parsers encode real format knowledge and are pinned by the
    accuracy tests. The token parser may only fill fields they left empty.
    """
    narration = "UPI/P2M/349488479088/Chalo/ICICI Ban/PayviaRa"
    from src.rules.bank_rules import icici_parse_description

    direct = icici_parse_description(narration)
    through_dispatch = get_description_parser("ICICI")(narration)

    for key, value in direct.items():
        if value:
            assert through_dispatch[key] == value, f"fallback overwrote {key}"


def test_empty_and_junk_input_is_safe():
    for narration in ("", "   ", "-", "///", None):
        result = token_parse_description(narration)
        assert set(result) == {"payee", "vpa", "ref", "remarks", "rail"}

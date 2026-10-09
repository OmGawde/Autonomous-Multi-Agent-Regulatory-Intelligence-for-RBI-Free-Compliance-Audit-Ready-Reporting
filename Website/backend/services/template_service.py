import json
import os
from pathlib import Path

PROJECT_ROOT_TEMPLATES = Path(__file__).parent.parent.parent.parent / "templates" / "banks.json"
BACKEND_TEMPLATES = Path(__file__).parent.parent / "templates" / "banks.json"

TEMPLATE_PATH = PROJECT_ROOT_TEMPLATES if PROJECT_ROOT_TEMPLATES.exists() else BACKEND_TEMPLATES

import re

class TemplateService:
    def __init__(self):
        # Create templates directory if not exists
        TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not TEMPLATE_PATH.exists():
            with open(TEMPLATE_PATH, "w") as f:
                json.dump({"Other": {"columns": {"date": None, "description": None, "debit": None, "credit": None, "balance": None}, "date_format": None}}, f, indent=2)
        
        with open(TEMPLATE_PATH, "r") as f:
            self.templates = json.load(f)

    def _reload(self):
        """Reload templates from disk (called after a write)."""
        with open(TEMPLATE_PATH, "r") as f:
            self.templates = json.load(f)

    def get_bank_config(self, bank_name: str) -> dict:
        """Finds bank config using case-insensitive and fuzzy alias matching."""
        if not bank_name:
            return self.templates.get("Other", {})

        # Direct match
        if bank_name in self.templates:
            return self.templates[bank_name]

        # Case-insensitive match
        for key, config in self.templates.items():
            if key.upper() == bank_name.upper():
                return config

        # Normalized alias match (e.g. "AXIS BANK" -> "Axis", "STATE BANK OF INDIA" -> "SBI")
        target_clean = re.sub(r'[^a-zA-Z0-9]', '', bank_name).lower()
        
        aliases = {
            "axisbank": "Axis",
            "axis": "Axis",
            "sbi": "SBI",
            "statebankofindia": "SBI",
            "hdfcbank": "HDFC",
            "hdfc": "HDFC",
            "icicibank": "ICICI",
            "icici": "ICICI",
            "kotak": "Kotak",
            "kotakmahindra": "Kotak",
            "kotakmahindrabank": "Kotak",
            "bankofbaroda": "BOB",
            "bob": "BOB",
            "baroda": "BOB",
            "bankofindia": "Bank Of India",
            "boi": "Bank Of India",
            "unionbank": "Union",
            "unionbankofindia": "Union",
            "union": "Union",
            "punjabnationalbank": "Punjab National Bank",
            "punjabnational": "Punjab National Bank",
            "pnb": "Punjab National Bank",
            "yesbank": "YES Bank",
            "yes": "YES Bank",
            "bankofmaharashtra": "Bank Of Maharashtra",
            "mahabank": "Bank Of Maharashtra",
            "bom": "Bank Of Maharashtra",
            "federalbank": "Federal Bank",
            "federal": "Federal Bank",
            "indianoverseasbank": "Indian Overseas Bank",
            "iob": "Indian Overseas Bank",
            "indusindbank": "IndusInd Bank",
            "indusind": "IndusInd Bank",
            "canarabank": "Canara Bank",
            "canara": "Canara Bank",
            "idbibank": "IDBI Bank",
            "idbi": "IDBI Bank"
        }
        
        if target_clean in aliases and aliases[target_clean] in self.templates:
            return self.templates[aliases[target_clean]]

        for key, config in self.templates.items():
            key_clean = re.sub(r'[^a-zA-Z0-9]', '', key).lower()
            if key_clean and (key_clean in target_clean or target_clean in key_clean):
                return config

        return self.templates.get("Other", {})

    def get_column_mapping(self, bank_name: str) -> dict:
        """Returns the column mapping for a given bank."""
        bank_config = self.get_bank_config(bank_name)
        return bank_config.get("columns", {})

    def get_all_bank_names(self) -> list[str]:
        """Returns a list of all supported bank names (excluding 'Other')."""
        return [k for k in self.templates.keys() if k != "Other"]

    def get_date_format(self, bank_name: str) -> str | None:
        """Returns the date format for a given bank."""
        bank_config = self.get_bank_config(bank_name)
        return bank_config.get("date_format")

    def get_vertical_lines(self, bank_name: str) -> list[float] | None:
        """Returns explicit vertical column X positions for a given bank, if saved."""
        bank_config = self.get_bank_config(bank_name)
        return bank_config.get("vertical_lines")

    def bank_exists(self, bank_name: str) -> bool:
        """Returns True if the bank name is already a known template."""
        config = self.get_bank_config(bank_name)
        return config != self.templates.get("Other", {})

    def save_bank_template(
        self,
        bank_name: str,
        vertical_lines_norm: list[float] | None = None,
        date_format: str | None = None,
        column_roles: list[str] | None = None,
        table_region_norm: dict | None = None,
        ifsc_prefix: str | None = None,
        detect_markers: list[str] | None = None,
    ) -> None:
        """
        Save (or update) a calibrated bank template.

        Merges into any existing entry rather than replacing it. The previous
        version assigned a freshly-built dict over `self.templates[bank_name]`,
        so calibrating a bank that already had a hand-written template wiped its
        column mapping to nulls -- `Website/backend/templates/banks.json` still
        carries the evidence, with ICICI, Axis and PNB reduced to all-null
        columns and nothing but vertical lines left.

        Geometry is stored NORMALISED (0..1 of page width). Absolute PDF points
        would silently break the moment a bank issues the same statement on a
        different page size.
        """
        existing = dict(self.templates.get(bank_name) or {})

        if vertical_lines_norm:
            existing["vertical_lines_norm"] = [float(x) for x in vertical_lines_norm]
        if table_region_norm:
            existing["table_region_norm"] = table_region_norm
        if date_format:
            existing["date_format"] = date_format
        if column_roles:
            # Explicit vertical lines produce a fixed, ordered set of columns, so
            # the extractor's existing positional mapping is exactly the right
            # consumer -- index -> role, no header text needed.
            existing["column_positions"] = {
                "expected_cols": len(column_roles),
                "mapping": {str(i): role for i, role in enumerate(column_roles)},
            }
        # How this bank will be recognised on a future upload. Without at least
        # one of these the template is unreachable by auto-detection and the
        # operator has to type the name exactly.
        if ifsc_prefix:
            existing["ifsc_prefix"] = ifsc_prefix.strip().upper()[:4]
        if detect_markers:
            existing["detect_markers"] = [m.strip() for m in detect_markers if str(m).strip()]

        existing.setdefault("columns", {})
        existing["calibrated"] = True

        self.templates[bank_name] = existing

        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, indent=2)
        self._reload()

    def delete_bank_template(self, bank_name: str) -> bool:
        """Remove a calibrated template. Refuses to delete a built-in one."""
        entry = self.templates.get(bank_name)
        if not entry:
            return False
        if not entry.get("calibrated"):
            raise ValueError(
                f"'{bank_name}' is a built-in template, not a calibrated one; refusing to delete it."
            )
        del self.templates[bank_name]
        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, indent=2)
        self._reload()
        return True

"""Unit tests for the GhostTrace deletion audit engine."""
from __future__ import annotations

import csv
import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from audit.data import Identity, IdentityIndex, email_hash, read_csv
from audit.engine import (
    FIND_ORDER,
    OP_STATE,
    REM_ORDER,
    TREATMENT_OPS,
    VER_ORDER,
    Auditor,
    ResourceView,
)
from audit.evidence import category_of, norm_phone, system_of
from audit.intent import heuristic_intent

import os

def find_dataset() -> Path:
    if "DATASET_DIR" in os.environ:
        return Path(os.environ["DATASET_DIR"]).resolve()
    candidates = [
        Path(__file__).resolve().parents[2] / "dataset",
        Path.cwd() / "dataset",
        Path(__file__).resolve().parents[1] / "dataset",
    ]
    for c in candidates:
        if c.exists() and (c / "deletion_rules.csv").exists():
            return c.resolve()
    return candidates[0].resolve()

D = find_dataset()
UTC = timezone.utc



class OutputTests(unittest.TestCase):
    def test_op_states_match_specification(self):
        expected = {
            "REPORT_REMAINING_RECORD": "PRESENT",
            "REPORT_EXPOSED_PII": "PRESENT",
            "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
            "REPORT_RESTORE_RISK": "ACTIVE",
            "DISABLE_DATA_FLOW": "DISABLED",
            "BLOCK_RESTORE": "BLOCKED",
            "DELETE_RECORD": "ABSENT",
            "REDACT_RECORD": "REDACTED",
            "ANONYMIZE_RECORD": "ANONYMIZED",
            "VERIFY_RECORD_ABSENT": "ABSENT",
            "VERIFY_RECORD_PRESENT": "PRESENT",
            "VERIFY_RECORD_REDACTED": "REDACTED",
            "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
            "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
            "VERIFY_RESTORE_BLOCKED": "BLOCKED",
        }
        for op, state in expected.items():
            self.assertEqual(OP_STATE[op], state)

    def test_ordering_contract(self):
        auditor = Auditor.__new__(Auditor)
        findings = [
            ("REPORT_EXPOSED_PII", ResourceView("support_platform", "support_864", "SUPPORT_ATTACHMENT"), "evidence_03"),
            ("REPORT_REMAINING_RECORD", ResourceView("search_service", "search_052", "SEARCH_INDEX_RECORD"), "evidence_03"),
            ("REPORT_ACTIVE_DATA_FLOW", ResourceView("integration_service", "data_flow_9522", "CONNECTOR_SCHEDULE"), "evidence_03"),
        ]
        rems = [
            ("DISABLE_DATA_FLOW", ResourceView("integration_service", "data_flow_9522", "CONNECTOR_SCHEDULE")),
            ("DELETE_RECORD", ResourceView("search_service", "search_052", "SEARCH_INDEX_RECORD")),
            ("REDACT_RECORD", ResourceView("support_platform", "support_864", "SUPPORT_ATTACHMENT")),
        ]
        vers = [
            ("VERIFY_DATA_FLOW_DISABLED", ResourceView("integration_service", "data_flow_9522", "CONNECTOR_SCHEDULE"), ""),
            ("VERIFY_RECORD_ABSENT", ResourceView("search_service", "search_052", "SEARCH_INDEX_RECORD"), ""),
            ("VERIFY_RECORD_REDACTED", ResourceView("support_platform", "support_864", "SUPPORT_ATTACHMENT"), ""),
        ]
        steps = auditor.build_steps(findings, rems, vers, complete=False)

        # 1. Step numbers must be consecutive 1..N
        self.assertEqual([s["step_no"] for s in steps], list(range(1, len(steps) + 1)))

        # 2. Phase order: FINDING -> REMEDIATION -> VERIFICATION
        phases = [s["phase"] for s in steps]
        f_idx = [i for i, p in enumerate(phases) if p == "FINDING"]
        r_idx = [i for i, p in enumerate(phases) if p == "REMEDIATION"]
        v_idx = [i for i, p in enumerate(phases) if p == "VERIFICATION"]
        self.assertTrue(max(f_idx) < min(r_idx) < max(r_idx) < min(v_idx))

        # 3. Future remediation and verification steps must have empty evidence_id
        for s in steps:
            if s["phase"] in ("REMEDIATION", "VERIFICATION"):
                self.assertEqual(s["evidence_id"], "")
            else:
                self.assertTrue(bool(s["evidence_id"]))


class IdentityTests(unittest.TestCase):
    def setUp(self):
        if (D / "user_identities.csv").exists():
            identities_rows = read_csv(D / "user_identities.csv")
            audit_rows = read_csv(D / "user_audit_log.csv")
        else:
            identities_rows = [
                {"user_id": "user_12", "name": "Min-Jun Kim", "email": "minjun.kim90@gmail.com", "phone": "+82 10 9876 5432", "email_hash": email_hash("minjun.kim90@gmail.com"), "updated_at": "2026-03-21T20:59:00Z"},
                {"user_id": "user_36", "name": "Sipho Mokoena", "email": "sipho.mokoena@gmail.com", "phone": "+27 82 555 0192", "email_hash": email_hash("sipho.mokoena@gmail.com"), "updated_at": "2026-03-21T20:59:00Z"},
            ]
            audit_rows = [
                {"audit_id": "audit_1", "user_id": "user_12", "field_name": "email", "old_value": "minjun.kim@gmail.com", "new_value": "minjun.kim90@gmail.com", "event_time": "2026-01-15T10:00:00Z"},
            ]
        self.index = IdentityIndex(identities_rows, audit_rows)

    def test_historical_email_resolution(self):
        # minjun.kim90@gmail.com changed from historical minjun.kim@gmail.com
        ident = self.index.resolve("minjun.kim@gmail.com")
        self.assertEqual(ident.user_id, "user_12")
        self.assertIn("minjun.kim90@gmail.com", ident.emails)
        self.assertIn("minjun.kim@gmail.com", ident.emails)
        self.assertIn(email_hash("minjun.kim90@gmail.com"), ident.hashes)

    def test_case_insensitivity(self):
        ident = self.index.resolve("SIPHO.MOKOENA@GMAIL.COM")
        self.assertEqual(ident.user_id, "user_36")

    def test_phone_normalization(self):
        self.assertEqual(norm_phone("+1 (555) 019-2834"), "tel:15550192834")
        self.assertEqual(norm_phone("555-019-2834"), "tel:5550192834")

    def test_unknown_identity_fallback(self):
        ident = self.index.resolve("unknown.ghost@example.com")
        self.assertEqual(ident.user_id, "")
        self.assertIn("unknown.ghost@example.com", ident.emails)
        self.assertIn(email_hash("unknown.ghost@example.com"), ident.hashes)


class TemporalTests(unittest.TestCase):
    def test_cutoff_boundary(self):
        from audit.evidence import Observation
        from audit.engine import ts

        cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        o_valid = Observation("ev_1", "2026-05-30T10:00:00Z", "2026-05-30T10:00:00Z", "sys", "res_1", "CAT", "PRESENT", set())
        o_future = Observation("ev_2", "2026-06-02T10:00:00Z", "2026-06-02T10:00:00Z", "sys", "res_1", "CAT", "ABSENT", set())

        self.assertTrue(ts(o_valid.available_at) <= cutoff)
        self.assertFalse(ts(o_future.available_at) <= cutoff)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        if (D / "deletion_rules.csv").exists():
            self.rules = read_csv(D / "deletion_rules.csv")
            self.treatment = {r["data_category"]: r["required_action"] for r in self.rules}
        else:
            self.treatment = {
                "USER_PROFILE": "DELETE",
                "SEARCH_INDEX_ENTRY": "DELETE",
                "SUPPORT_MESSAGE": "REDACT",
                "SUPPORT_ATTACHMENT": "DELETE",
                "ANALYTICS_PROFILE": "ANONYMIZE",
                "SECURITY_AUDIT_LOG": "RETAIN",
                "ACCOUNT_TOMBSTONE": "REDACT",
            }

    def test_treatments_defined(self):
        self.assertEqual(self.treatment["USER_PROFILE"], "DELETE")
        self.assertEqual(self.treatment["SEARCH_INDEX_ENTRY"], "DELETE")
        self.assertEqual(self.treatment["SUPPORT_MESSAGE"], "REDACT")
        self.assertEqual(self.treatment["SUPPORT_ATTACHMENT"], "DELETE")
        self.assertEqual(self.treatment["ANALYTICS_PROFILE"], "ANONYMIZE")
        self.assertEqual(self.treatment["SECURITY_AUDIT_LOG"], "RETAIN")
        self.assertEqual(self.treatment["ACCOUNT_TOMBSTONE"], "REDACT")


class IntentTests(unittest.TestCase):
    def test_deletion_and_non_deletion_heuristics(self):
        # Explicit deletion
        self.assertTrue(heuristic_intent("Please delete all my personal data and close my account."))
        self.assertTrue(heuristic_intent("Por favor elimine mi cuenta y mis datos."))
        self.assertTrue(heuristic_intent("계정 영구 삭제 및 개인정보 파기를 요청합니다."))
        self.assertTrue(heuristic_intent("Veuillez supprimer mon compte et mes informations personnelles."))

        # Non-deletion requests
        self.assertFalse(heuristic_intent("I only want to unsubscribe from promotional marketing emails."))
        self.assertFalse(heuristic_intent("Please send me a download of all my invoices and receipts."))
        self.assertFalse(heuristic_intent("I need help resetting my account password."))
        self.assertFalse(heuristic_intent("Please do not delete my account, just update my address."))


class EvidenceFallbackTests(unittest.TestCase):
    def test_pdf_extraction_fallback_without_optional_libraries(self):
        import sys
        import tempfile
        from audit.evidence import pdf_text

        # Temporarily mock out pdfplumber and pypdf to test stdlib fallback
        orig_pdfplumber = sys.modules.get("pdfplumber")
        orig_pypdf = sys.modules.get("pypdf")
        sys.modules["pdfplumber"] = None
        sys.modules["pypdf"] = None

        try:
            pdf_path = D / "evidence" / "documents" / "account_history_report_20260718.pdf"
            if pdf_path.exists():
                text = pdf_text(pdf_path)
                self.assertIn("NORTHSTAR SHOP", text)
                self.assertIn("Statement NST-2026-0718-1842", text)
                self.assertIn("user_18", text)
                self.assertIn("ingrid.dahl@outlook.com", text)

                correction_path = D / "evidence" / "documents" / "delivery_correction_attachment.pdf"
                corr_text = pdf_text(correction_path)
                self.assertIn("DELIVERY ADDRESS CORRECTION REQUEST", corr_text)
                self.assertIn("CS-4827", corr_text)
                self.assertIn("support_001", corr_text)
                self.assertIn("priya.raman@gmail.com", corr_text)
                self.assertIn("+91 98765 73142", corr_text)

                legal_path = D / "evidence" / "documents" / "legal_retention_register_20260529.pdf"
                legal_text = pdf_text(legal_path)
                self.assertIn("DISPUTED ORDERS AND TAX RECORDS REGISTER", legal_text)
                self.assertIn("ORD-20264118", legal_text)
                self.assertIn("user_08", legal_text)
                self.assertIn("Retain until 04 May 2033", legal_text)
                self.assertIn("ORD-20264207", legal_text)
                self.assertIn("user_12", legal_text)

                sec_path = D / "evidence" / "documents" / "security_retention_extract.pdf"
                sec_text = pdf_text(sec_path)
                self.assertIn("COMPLIANCE JOURNAL - SIGNED RECORD EXTRACT", sec_text)
                self.assertIn("Reference CJX-20260905-0630", sec_text)
                self.assertIn("subject reference user_03", sec_text)
            else:
                synth = (
                    b"%PDF-1.4\n1 0 obj\n<< /Length 120 >>\nstream\nBT\n/F1 12 Tf\n"
                    b"(NORTHSTAR SHOP - CUSTOMER STATEMENT) Tj\n"
                    b"(Statement NST-2026-0718-1842) Tj\n"
                    b"(user_18) Tj\nET\nendstream\nendobj\nxref\n0 2\n0000000000 65535 f\n"
                    b"0000000009 00000 n\ntrailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n190\n%%EOF"
                )
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(synth)
                    tmp_p = Path(f.name)
                try:
                    text = pdf_text(tmp_p)
                    self.assertIn("NORTHSTAR SHOP", text)
                    self.assertIn("Statement NST-2026-0718-1842", text)
                    self.assertIn("user_18", text)
                finally:
                    tmp_p.unlink()
        finally:
            if orig_pdfplumber is not None:
                sys.modules["pdfplumber"] = orig_pdfplumber
            else:
                sys.modules.pop("pdfplumber", None)
            if orig_pypdf is not None:
                sys.modules["pypdf"] = orig_pypdf
            else:
                sys.modules.pop("pypdf", None)


if __name__ == "__main__":
    unittest.main()

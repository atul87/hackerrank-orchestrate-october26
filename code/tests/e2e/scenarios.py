"""Hand-labelled end-to-end scenarios (SPEC §13.3). Each returns (dataset, {case_id: (status, steps)}).

Expected steps are derived by hand from the public contract (problem statement + deletion rules), not by
running the engine: phases FINDING -> REMEDIATION -> VERIFICATION, operations in contract-table order, then
system_id and resource_id; findings cite the evidence that shows the violation, future steps cite nothing,
and COMPLETE cases cite the latest evidence proving each compliant state.
"""
from __future__ import annotations

try:
    from .builder import MiniDataset, sha
except ImportError:
    from builder import MiniDataset, sha

REQ, REP, AUD = "2026-05-01T09:00:00Z", "2026-05-03T09:00:00Z", "2026-05-10T12:00:00Z"
EMAIL, OLD_EMAIL = "lena.novak@example.org", "l.novak@example.org"
ACC = "rows=0 http_status=404"


def base() -> MiniDataset:
    return MiniDataset().user("user_101", "Lena Novak", EMAIL, "+48 600 100 200")


def F(sys, rid, op, ev):
    state = {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
             "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE"}[op]
    return ("FINDING", sys, rid, op, state, ev)


def R(sys, rid, op):
    state = {"DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED", "ANONYMIZE_RECORD": "ANONYMIZED",
             "BLOCK_RESTORE": "BLOCKED", "DISABLE_DATA_FLOW": "DISABLED"}[op]
    return ("REMEDIATION", sys, rid, op, state, "")


def V(sys, rid, op, ev=""):
    state = {"VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT", "VERIFY_RECORD_REDACTED": "REDACTED",
             "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED", "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
             "VERIFY_RESTORE_BLOCKED": "BLOCKED"}[op]
    return ("VERIFICATION", sys, rid, op, state, ev)


def profile_lookup(rid, key, kv=ACC, ts="2026-05-10T08:00:00Z"):
    return (ts, "account_service", "profile_lookup", rid, key, kv)


def search_lookup(rid, key, hit=True, email=None, ts="2026-05-10T08:05:00Z"):
    kv = (f"result=hit total_hits=1 index=customer_directory_v3 email={email or key} customer_reference=null" if hit
          else "result=miss total_hits=0 index=customer_directory_v3")
    return (ts, "search_service", "index_query", rid, key, kv)


def profile_deletion(ds: MiniDataset, rid: str, at: str = "2026-05-03T08:00:00Z"):
    ds.act(at, "DELETE_RECORD", "deletion_worker", "account_service", rid, "SUCCESS",
           f"Deletion worker submitted primary profile {rid} to account_service.")


# 1 -----------------------------------------------------------------------------------------------------------
def historical_email_only():
    ds = base().change("user_101", "email", OLD_EMAIL, EMAIL, "2026-03-01T10:00:00Z")
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7001", EMAIL),
                                             search_lookup("search_7002", OLD_EMAIL)])
    ds.request("case_01", OLD_EMAIL, REQ, REP, AUD)
    return ds, {"case_01": ("INCOMPLETE", [
        F("search_service", "search_7002", "REPORT_REMAINING_RECORD", "evidence_01"),
        R("search_service", "search_7002", "DELETE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("search_service", "search_7002", "VERIFY_RECORD_ABSENT"),
    ])}


# 2 -----------------------------------------------------------------------------------------------------------
def near_miss_decoys():
    ds = base().user("user_102", "Lena Nowak", "lena.novak.jr@example.org", "+48 600 100 201") \
               .user("user_103", "Lena Novak", "lena.novak1@example.org", "+48 600 100 202")
    ds.readback_log("2026-05-10T10:00:00Z", [
        profile_lookup("account_7001", EMAIL),
        search_lookup("search_7100", "lena.novak.jr@example.org"),
        profile_lookup("account_7101", "lena.novak1@example.org", "rows=1 http_status=200 email=lena.novak1@example.org"),
    ])
    ds.request("case_02", EMAIL, REQ, REP, AUD)
    return ds, {"case_02": ("COMPLETE", [V("account_service", "account_7001", "VERIFY_RECORD_ABSENT", "evidence_01")])}


# 3 -----------------------------------------------------------------------------------------------------------
def evidence_after_audit_is_ignored():
    ds = base()
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7001", EMAIL)])
    ds.service_export_json("2026-05-20T10:00:00Z", {"search_service": {"index_queries": [{
        "observed_at": "2026-05-20T09:00:00Z", "query": EMAIL, "resource_id": "search_7002",
        "hits": {"total": 1, "documents": [{"resource_id": "search_7002", "email": EMAIL}]}}]}})
    ds.request("case_03", EMAIL, REQ, REP, AUD)
    return ds, {"case_03": ("COMPLETE", [V("account_service", "account_7001", "VERIFY_RECORD_ABSENT", "evidence_01")])}


# 4 -----------------------------------------------------------------------------------------------------------
def korean_non_deletion_request():
    ds = base()
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7001", EMAIL, f"rows=1 http_status=200 email={EMAIL}")])
    ds.request("case_04", EMAIL, REQ, REP, AUD, text="계정은 그대로 유지해 주세요. 마케팅 이메일 수신만 중단하고 데이터는 삭제하지 마세요.",
               status="NOT_STARTED")
    return ds, {"case_04": ("NOT_APPLICABLE", [])}


# 5 -----------------------------------------------------------------------------------------------------------
def success_claim_is_not_proof():
    ds = base()
    ds.act("2026-05-02T10:00:00Z", "DELETE_RECORD", "deletion_worker", "search_service", "search_7002", "SUCCESS",
           "Deletion worker received the final result for search_7002 from search_service.")
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7001", EMAIL), search_lookup("search_7002", EMAIL)])
    ds.request("case_05", EMAIL, REQ, REP, AUD)
    return ds, {"case_05": ("INCOMPLETE", [
        F("search_service", "search_7002", "REPORT_REMAINING_RECORD", "evidence_01"),
        R("search_service", "search_7002", "DELETE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("search_service", "search_7002", "VERIFY_RECORD_ABSENT"),
    ])}


# 6 -----------------------------------------------------------------------------------------------------------
def failover_replica_drift():
    ds = base().user("user_104", "Piotr Zielinski", "p.zielinski@example.org", "+48 600 100 300")
    ds.failover_sql("2026-05-10T09:00:00Z",
                    primary=[("account_7200", "user_104", "Piotr Zielinski", "p.zielinski@example.org", "+48 600 100 300", "ACTIVE", "2026-05-10T08:00:00Z")],
                    failover=[("account_7200", "user_104", "Piotr Zielinski", "p.zielinski@example.org", "+48 600 100 300", "ACTIVE", "2026-05-10T08:00:00Z"),
                              ("account_7001", "user_101", "Lena Novak", EMAIL, "+48 600 100 200", "ACTIVE", "2026-05-10T08:00:00Z")])
    ds.request("case_06", EMAIL, REQ, REP, AUD)
    return ds, {"case_06": ("INCOMPLETE", [
        F("account_service", "account_7001", "REPORT_REMAINING_RECORD", "evidence_01"),
        R("account_service", "account_7001", "DELETE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
    ])}


# 7 -----------------------------------------------------------------------------------------------------------
def connector_recreates_deleted_entry():
    ds = base()
    ds.readback_log("2026-05-05T10:00:00Z", [profile_lookup("account_7001", EMAIL, ts="2026-05-05T08:00:00Z"),
                                             search_lookup("search_7002", EMAIL, hit=False, ts="2026-05-05T08:05:00Z")])
    ds.act("2026-05-08T06:00:00Z", "SYNC_RECORD", "integration_service", "search_service", "data_flow_7003", "SUCCESS",
           "Active connector repopulated downstream resource search_7002.")
    ds.request("case_07", EMAIL, REQ, REP, AUD)
    return ds, {"case_07": ("INCOMPLETE", [
        F("search_service", "search_7002", "REPORT_REMAINING_RECORD", "activity_01"),
        F("integration_service", "data_flow_7003", "REPORT_ACTIVE_DATA_FLOW", "activity_01"),
        R("integration_service", "data_flow_7003", "DISABLE_DATA_FLOW"),
        R("search_service", "search_7002", "DELETE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("search_service", "search_7002", "VERIFY_RECORD_ABSENT"),
        V("integration_service", "data_flow_7003", "VERIFY_DATA_FLOW_DISABLED"),
    ])}


# 8 -----------------------------------------------------------------------------------------------------------
def restorable_backup():
    ds = base()
    profile_deletion(ds, "account_7001")
    ds.inventory_sql("2026-05-10T09:00:00Z", ["account_service", "backup_service"], [
        f"INSERT INTO backup_restore_entries VALUES ('backup_7004', NULL, '{EMAIL}', 'archive/customer-data/backup_7004.tar.zst', '1', '2026-05-10T08:00:00Z')",
    ])
    ds.request("case_08", EMAIL, REQ, REP, AUD)
    return ds, {"case_08": ("INCOMPLETE", [
        F("backup_service", "backup_7004", "REPORT_RESTORE_RISK", "evidence_01"),
        R("backup_service", "backup_7004", "BLOCK_RESTORE"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("backup_service", "backup_7004", "VERIFY_RESTORE_BLOCKED"),
    ])}


# 9 -----------------------------------------------------------------------------------------------------------
def tombstones_exposed_and_clean():
    ds = base().user("user_103", "Omar Haddad", "omar.h@example.org", "+971 50 100 2000")
    profile_deletion(ds, "account_7001", "2026-05-03T08:00:00Z")
    profile_deletion(ds, "account_7301", "2026-05-06T08:00:00Z")
    ds.bundle_json("2026-05-10T09:00:00Z", [
        ("account_service", "customer_profiles", []),
        ("identity_service", "deleted_customer_references", [
            {"resource_id": "tombstone_7005", "subject_reference": "user_101", "name": "Lena Novak", "email": EMAIL,
             "phone": "+48 600 100 200", "email_hash": sha(EMAIL), "account_status": "DELETED"},
            {"resource_id": "tombstone_7006", "subject_reference": "user_103", "name": None, "email": None,
             "phone": None, "email_hash": None, "account_status": "DELETED"}]),
    ])
    ds.request("case_09", EMAIL, REQ, REP, AUD)
    ds.request("case_10", "omar.h@example.org", "2026-05-04T09:00:00Z", "2026-05-06T09:00:00Z", AUD)
    return ds, {
        "case_09": ("INCOMPLETE", [
            F("identity_service", "tombstone_7005", "REPORT_EXPOSED_PII", "evidence_01"),
            R("identity_service", "tombstone_7005", "REDACT_RECORD"),
            V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
            V("identity_service", "tombstone_7005", "VERIFY_RECORD_REDACTED"),
        ]),
        "case_10": ("COMPLETE", [
            V("account_service", "account_7301", "VERIFY_RECORD_ABSENT", "evidence_01"),
            V("identity_service", "tombstone_7006", "VERIFY_RECORD_REDACTED", "evidence_01"),
        ]),
    }


# 10 ----------------------------------------------------------------------------------------------------------
def support_message_vs_attachment():
    ds = base()
    profile_deletion(ds, "account_7001")
    ds.inventory_sql("2026-05-09T09:00:00Z", ["account_service", "support_platform"], [
        f"INSERT INTO support_records VALUES ('support_7007', NULL, NULL, '{EMAIL}', NULL, 'Customer asked support to correct delivery details.', '2026-05-09T08:00:00Z')",
    ])
    ds.bundle_json("2026-05-10T09:00:00Z", [("support_platform", "ticket_attachments", [
        {"resource_id": "support_7008", "ticket_id": "CS-7008", "file_name": "delivery_note_7008.pdf",
         "uploaded_by": EMAIL, "storage_class": "ticket_attachment"}])])
    ds.request("case_11", EMAIL, REQ, REP, AUD)
    return ds, {"case_11": ("INCOMPLETE", [
        F("support_platform", "support_7008", "REPORT_REMAINING_RECORD", "evidence_02"),
        F("support_platform", "support_7007", "REPORT_EXPOSED_PII", "evidence_01"),
        R("support_platform", "support_7008", "DELETE_RECORD"),
        R("support_platform", "support_7007", "REDACT_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("support_platform", "support_7008", "VERIFY_RECORD_ABSENT"),
        V("support_platform", "support_7007", "VERIFY_RECORD_REDACTED"),
    ])}


# 11 ----------------------------------------------------------------------------------------------------------
def retained_audit_and_legal_hold():
    ds = base()
    ds.readback_log("2026-05-10T10:00:00Z", [
        profile_lookup("account_7001", EMAIL),
        ("2026-05-10T08:10:00Z", "security_service", "audit_record_read", "audit_record_7009", "user_101",
         "rows=1 subject_reference=user_101 event_code=ACCOUNT_DELETION_RECORDED retention_until=2031-12-31T23:59:59Z"),
    ])
    ds.bundle_json("2026-05-10T09:00:00Z", [("legal_service", "retained_order_records", [
        {"resource_id": "legal_hold_7010", "subject_reference": "user_101", "order_reference": "ORD-7010",
         "retention_reason": "payment_dispute_and_tax_record", "retained_until": "2033-12-31T23:59:59Z"}])])
    ds.request("case_12", EMAIL, REQ, REP, AUD)
    return ds, {"case_12": ("COMPLETE", [
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT", "evidence_01"),
        V("legal_service", "legal_hold_7010", "VERIFY_RECORD_PRESENT", "evidence_02"),
        V("security_service", "audit_record_7009", "VERIFY_RECORD_PRESENT", "evidence_01"),
    ])}


# 12 ----------------------------------------------------------------------------------------------------------
def analytics_profile_vs_marketing_contact():
    ds = base()
    ds.readback_log("2026-05-10T10:00:00Z", [
        profile_lookup("account_7001", EMAIL),
        ("2026-05-10T08:20:00Z", "analytics_platform", "analytics_profile_read", "analytics_7011", EMAIL,
         f"customer_reference=null email={EMAIL} phone=null email_hash=null audience_cohort=general_shopper"),
    ])
    ds.evidence("evidence/logs/service_events_20260510.log", "2026-05-10T11:00:00Z",
                "2026-05-10T10:58:26Z level=DEBUG service=analytics_platform instance=analytics-2 trace_id=tr-9137340 "
                f"resource_id=analytics_7012 event=contact_lookup_completed rows=1 email_opt_in=true correlation_key=\"{sha(EMAIL)}\"\n",
                "central_observability_export")
    ds.request("case_13", EMAIL, REQ, REP, AUD)
    return ds, {"case_13": ("INCOMPLETE", [
        F("analytics_platform", "analytics_7012", "REPORT_REMAINING_RECORD", "evidence_02"),
        F("analytics_platform", "analytics_7011", "REPORT_EXPOSED_PII", "evidence_01"),
        R("analytics_platform", "analytics_7012", "DELETE_RECORD"),
        R("analytics_platform", "analytics_7011", "ANONYMIZE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("analytics_platform", "analytics_7012", "VERIFY_RECORD_ABSENT"),
        V("analytics_platform", "analytics_7011", "VERIFY_RECORD_ANONYMIZED"),
    ])}


# 13 ----------------------------------------------------------------------------------------------------------
def complete_cites_latest_evidence():
    ds = base()
    ds.readback_log("2026-05-01T10:00:00Z", [
        profile_lookup("account_7001", EMAIL, f"rows=1 http_status=200 email={EMAIL}", ts="2026-05-01T08:00:00Z"),
        search_lookup("search_7002", EMAIL, ts="2026-05-01T08:05:00Z")])
    ds.readback_log("2026-05-08T10:00:00Z", [
        profile_lookup("account_7001", EMAIL, ts="2026-05-08T08:00:00Z"),
        search_lookup("search_7002", EMAIL, hit=False, ts="2026-05-08T08:05:00Z")])
    ds.inventory_sql("2026-05-09T09:00:00Z", ["integration_service"], [
        f"INSERT INTO connector_subscriptions VALUES ('data_flow_7003', NULL, '{EMAIL}', 'customer_events_connector', '0', 'stopped', '2026-05-09T08:00:00Z')"])
    ds.request("case_14", EMAIL, REQ, REP, AUD)
    return ds, {"case_14": ("COMPLETE", [
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT", "evidence_02"),
        V("search_service", "search_7002", "VERIFY_RECORD_ABSENT", "evidence_02"),
        V("integration_service", "data_flow_7003", "VERIFY_DATA_FLOW_DISABLED", "evidence_03"),
    ])}


# 14 ----------------------------------------------------------------------------------------------------------
def identifiers_joined_across_trace_lines():
    ds = base()
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7001", EMAIL)])
    ds.split_trace_log("2026-05-10T11:00:00Z", "2026-05-10T10:30:00Z", "search_service", EMAIL, "search_7002",
                       "result=hit index=customer_directory_v3")
    ds.request("case_15", EMAIL, REQ, REP, AUD)
    return ds, {"case_15": ("INCOMPLETE", [
        F("search_service", "search_7002", "REPORT_REMAINING_RECORD", "evidence_02"),
        R("search_service", "search_7002", "DELETE_RECORD"),
        V("account_service", "account_7001", "VERIFY_RECORD_ABSENT"),
        V("search_service", "search_7002", "VERIFY_RECORD_ABSENT"),
    ])}


# 15 ----------------------------------------------------------------------------------------------------------
def unknown_identity_uses_bare_email():
    """Defined behaviour: an email that matches no identity is audited with the email and its hash only."""
    ds = base()
    ghost = "ghost.customer@example.org"
    ds.readback_log("2026-05-10T10:00:00Z", [profile_lookup("account_7013", ghost, f"rows=1 http_status=200 email={ghost}")])
    ds.request("case_16", ghost, REQ, REP, AUD)
    return ds, {"case_16": ("INCOMPLETE", [
        F("account_service", "account_7013", "REPORT_REMAINING_RECORD", "evidence_01"),
        R("account_service", "account_7013", "DELETE_RECORD"),
        V("account_service", "account_7013", "VERIFY_RECORD_ABSENT"),
    ])}


SCENARIOS = [
    historical_email_only, near_miss_decoys, evidence_after_audit_is_ignored, korean_non_deletion_request,
    success_claim_is_not_proof, failover_replica_drift, connector_recreates_deleted_entry, restorable_backup,
    tombstones_exposed_and_clean, support_message_vs_attachment, retained_audit_and_legal_hold,
    analytics_profile_vs_marketing_contact, complete_cites_latest_evidence, identifiers_joined_across_trace_lines,
    unknown_identity_uses_bare_email,
]

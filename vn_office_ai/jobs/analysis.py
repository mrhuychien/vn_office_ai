"""Background runner cho AI Analyst (Tier 2).

Chạy nền: gom dữ liệu (query nội bộ + parse file) → chunk → gọi LLM per chunk
→ ghi findings → status Ready For Review / Failed.
"""

import json

import frappe


def run_analysis(job_name):
    """Enqueued task. Chạy phân tích đầy đủ cho 1 Analysis Job."""
    job = frappe.get_doc("AI Office Analysis Job", job_name)
    atype = frappe.get_cached_doc("AI Office Analysis Type", job.analysis_type)
    try:
        data = _collect_data(job, atype)
        if not data:
            job.db_set("status", "Failed")
            job.db_set("error_message", "Không có dữ liệu để phân tích.")
            frappe.db.commit()
            return

        chunks = _chunk(data, atype.chunking_strategy, atype.max_chunk_size or 300)

        from vn_office_ai.llm.client import analyst_completion
        all_findings, tot_in, tot_out, tot_cost = [], 0, 0, 0.0
        for i, chunk in enumerate(chunks):
            frappe.publish_realtime(
                "aio_analysis_progress",
                {"job": job_name, "chunk": i + 1, "total": len(chunks)},
                user=job.requested_by,
            )
            res = analyst_completion(atype.prompt_system, chunk, atype.finding_schema)
            parsed = res.get("parsed") or {}
            all_findings.extend(parsed.get("findings", []))
            tot_in += res["input_tokens"]
            tot_out += res["output_tokens"]
            tot_cost += res["cost_usd"]

        _write_findings(job, all_findings)
        job.llm_input_tokens = tot_in
        job.llm_output_tokens = tot_out
        job.llm_cost_usd = tot_cost
        job.llm_chunks_processed = len(chunks)
        job.llm_model_used = atype.llm_model or ""
        job.status = "Ready For Review"
        job.recompute_counters()
        job.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        job.db_set("status", "Failed")
        job.db_set("error_message", str(e)[:500])
        frappe.log_error(frappe.get_traceback(), f"AIO run_analysis {job_name}")
        frappe.db.commit()


def _collect_data(job, atype):
    data = []
    if atype.input_mode in ("Internal Query Only", "Both"):
        from vn_office_ai.utils.data_source import execute_query_definition
        internal = execute_query_definition(
            atype, company=job.company,
            period_from=job.period_from, period_to=job.period_to,
        )
        job.db_set("internal_query_executed", 1)
        job.db_set("internal_data_row_count", len(internal))
        job.db_set("internal_data_summary", json.dumps(
            {"rows": len(internal), "sample": internal[:2]}, default=str, ensure_ascii=False))
        data.extend([_jsonable(r) for r in internal])
    if atype.input_mode in ("File Upload Only", "Both"):
        from vn_office_ai.utils.file_parser import parse_input_files
        file_rows = parse_input_files(job)
        job.save(ignore_permissions=True)  # lưu row_count/parsed của input_files
        data.extend([_jsonable(r) for r in file_rows])
    return data


_VALID_SEVERITY = {"Info", "Warning", "Critical"}
_VALID_ACTION = {"Create Document", "Modify Document", "Cancel Document", "No Action", "Manual Review"}
_ACTION_ALIASES = {
    "create draft": "Create Document", "create": "Create Document",
    "modify": "Modify Document", "cancel": "Cancel Document",
    "none": "No Action", "no action": "No Action", "review": "Manual Review",
}


def _coerce_severity(val):
    v = str(val or "").strip().title()
    return v if v in _VALID_SEVERITY else "Info"


def _coerce_action(val):
    v = str(val or "").strip()
    if v in _VALID_ACTION:
        return v
    return _ACTION_ALIASES.get(v.lower(), "Manual Review")


def _write_findings(job, raw_findings):
    job.set("findings", [])
    for idx, f in enumerate(raw_findings, 1):
        job.append("findings", {
            "finding_no": f"F-{idx:03d}",
            "severity": _coerce_severity(f.get("severity")),
            "finding_type": f.get("finding_type") or "Finding",
            "description": f.get("description") or "(không có mô tả)",
            "source_doctype": f.get("source_doctype") or None,
            "source_docname": f.get("source_docname") or None,
            "source_reference": f.get("source_reference"),
            "compliance_reference": f.get("compliance_reference"),
            "ai_confidence": f.get("ai_confidence") or 0,
            "suggested_action": _coerce_action(f.get("suggested_action")),
            "suggested_summary": f.get("suggested_summary") or "",
            "suggested_payload": json.dumps(f.get("suggested_payload", {}), ensure_ascii=False),
            "review_status": "Pending",
        })


def _chunk(data, strategy, size):
    """Chia dữ liệu thành chunk. By Row Count = đơn giản nhất; các strategy khác fallback."""
    if not data:
        return []
    if strategy in (None, "None"):
        return [data]
    if strategy == "By Account":
        return _group_by_key(data, "account")
    if strategy == "By Item":
        return _group_by_key(data, "item_code")
    if strategy == "By Date":
        return _group_by_key(data, "posting_date")
    # By Row Count (mặc định)
    return [data[i:i + size] for i in range(0, len(data), size)]


def _group_by_key(data, key):
    groups = {}
    for row in data:
        groups.setdefault(row.get(key, "_"), []).append(row)
    return list(groups.values())


def _jsonable(row):
    """Chuyển giá trị date/datetime/Decimal → str để JSON-serialize gửi LLM."""
    out = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (int, float, str, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out

"""Render output Tier 1 thành file (.docx / .pdf) và lưu vào File DocType.

2 engine theo template.render_engine:
- "AI HTML to DOCX": AI trả HTML → python-docx (doc generative: HĐLĐ, Biên bản họp)
- "Print Format": dùng Frappe Print Format mirror Word gốc (doc cố định: Phiếu thu)
"""

import io

import frappe


def render_output(req, html_body) -> str:
    """Render và lưu file. Returns file_url của File đã tạo.

    Args:
        req: AI Office Document Request
        html_body: HTML AI sinh ra (cho engine AI HTML to DOCX)
    """
    tpl = frappe.get_cached_doc("AI Office Template", req.template)

    if tpl.render_engine == "Print Format" and tpl.print_format:
        return _render_via_print_format(req, tpl)
    return _render_html_to_docx(req, tpl, html_body)


# ───────────────────────── AI HTML → DOCX ─────────────────────────

def _render_html_to_docx(req, tpl, html_body) -> str:
    """Convert HTML AI sinh → .docx bằng python-docx. Chèn letterhead công ty nếu có."""
    from docx import Document as DocxDocument
    from docx.shared import Pt
    from bs4 import BeautifulSoup

    doc = DocxDocument()
    _apply_base_style(doc, Pt)

    company = _resolve_company_name(req)
    soup = BeautifulSoup(html_body or "", "html.parser")

    # thay placeholder {{COMPANY}}
    if company:
        for node in soup.find_all(string=lambda s: s and "{{COMPANY}}" in s):
            node.replace_with(node.replace("{{COMPANY}}", company))

    _html_nodes_to_docx(soup, doc, Pt)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    file_name = f"{req.name}_{tpl.template_code}.docx"
    return _save_file(req, file_name, buf.read())


def _apply_base_style(doc, Pt):
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(13)


def _html_nodes_to_docx(soup, doc, Pt):
    """Duyệt các thẻ top-level: h1-h4, p, table, ol/ul → paragraph/table trong docx.

    Đây là converter tối giản (đủ cho văn bản hành chính). Bảng phức tạp/CSS
    nâng cao không hỗ trợ — đó là lý do doc cố định nên dùng Print Format.
    """
    body = soup.body or soup
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "table", "ol", "ul"], recursive=True):
        name = el.name
        if name in ("h1", "h2", "h3", "h4"):
            level = int(name[1])
            p = doc.add_heading(el.get_text(strip=True), level=min(level, 4))
        elif name == "p":
            p = doc.add_paragraph(el.get_text(" ", strip=True))
        elif name in ("ol", "ul"):
            style = "List Number" if name == "ol" else "List Bullet"
            for li in el.find_all("li", recursive=False):
                doc.add_paragraph(li.get_text(" ", strip=True), style=style)
        elif name == "table":
            _table_to_docx(el, doc)


def _table_to_docx(table_el, doc):
    rows = table_el.find_all("tr")
    if not rows:
        return
    cols = max(len(r.find_all(["td", "th"])) for r in rows)
    t = doc.add_table(rows=0, cols=cols)
    t.style = "Table Grid"
    for r in rows:
        cells = r.find_all(["td", "th"])
        row_cells = t.add_row().cells
        for i, c in enumerate(cells):
            if i < cols:
                row_cells[i].text = c.get_text(" ", strip=True)


# ───────────────────────── Print Format ─────────────────────────

def _render_via_print_format(req, tpl) -> str:
    """Render qua Frappe Print Format → PDF (mirror Word gốc).

    Print Format được viết để nhận context là chính Document Request
    (truy cập field_values qua doc). PDF là output deterministic.
    """
    from frappe.utils.pdf import get_pdf

    html = frappe.get_print(
        doctype=req.doctype,
        name=req.name,
        print_format=tpl.print_format,
        no_letterhead=0,
    )
    pdf_bytes = get_pdf(html)
    file_name = f"{req.name}_{tpl.template_code}.pdf"
    return _save_file(req, file_name, pdf_bytes)


# ───────────────────────── shared ─────────────────────────

def _save_file(req, file_name, content) -> str:
    """Lưu nội dung thành File gắn vào Document Request. Returns file_url."""
    f = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "attached_to_doctype": req.doctype,
        "attached_to_name": req.name,
        "is_private": 1,
        "content": content,
    })
    f.insert(ignore_permissions=True)
    return f.file_url


def _resolve_company_name(req):
    """Tìm tên công ty: từ source record (nếu có field company) hoặc default company."""
    if req.source_docname and req.source_doctype:
        company = frappe.db.get_value(req.source_doctype, req.source_docname, "company")
        if company:
            return company
    return frappe.defaults.get_user_default("Company") or frappe.db.get_default("company")


# ═══════════════════════════ Tier 2 — commit findings → submittable draft ═══════════════════════════

import json
from jinja2 import Template

# Map số hiệu TK (account_number) TT200 → resolve theo company khi commit.
# Tránh hard-code TÊN tài khoản (có hậu tố công ty). Số hiệu TK ổn định theo CoA TT200.
TT200_ACCOUNTS = {
    "doubtful_expense": "6426",   # Chi phí dự phòng (quản lý DN)
    "doubtful_provision": "2293",  # Dự phòng phải thu khó đòi
}


def commit_job(job, retry_only=False):
    """Tạo chứng từ nháp (JE/SR/PE) từ findings Approved/Modified.

    Graceful partial: 1 finding lỗi không chặn finding khác (ghi commit_error).
    Hỗ trợ 2 chế độ qua output_mapping_jinja:
      - sentinel 'GROUP_BY_JOB' → gộp tất cả finding thành 1 chứng từ (VD dự phòng TT48)
      - Jinja thường → mỗi finding 1 chứng từ
    """
    atype = frappe.get_cached_doc("AI Office Analysis Type", job.analysis_type)
    mapping = (atype.output_mapping_jinja or "").strip()

    if atype.output_action == "Report Only":
        result = _commit_report_only(job)
    elif mapping == "GROUP_BY_JOB":
        result = _commit_grouped(job, atype, retry_only)
    else:
        result = _commit_per_finding(job, atype, mapping, retry_only)

    job.status = "Committed"
    job.save()
    return result


def _commit_report_only(job):
    """Output Action = Report Only: đánh dấu approved/modified là đã ghi nhận, không tạo chứng từ."""
    now = frappe.utils.now_datetime()
    n = 0
    for f in job.findings:
        if f.review_status in ("Approved", "Modified") and not f.committed:
            f.committed = 1
            f.committed_at = now
            f.commit_error = None
            n += 1
    return {"created": n, "failed": 0, "status": "Committed", "report_only": True}


def _commit_per_finding(job, atype, mapping, retry_only):
    created, failed = 0, 0
    for f in job.findings:
        if f.review_status not in ("Approved", "Modified"):
            continue
        if f.committed:
            continue
        payload = json.loads(f.final_payload or f.suggested_payload or "{}")
        try:
            doc_dict = _render_mapping(mapping, payload, job)
            out = frappe.get_doc(doc_dict)
            out.insert()  # docstatus 0 — KHÔNG submit
            f.committed = 1
            f.committed_doctype = out.doctype
            f.committed_docname = out.name
            f.committed_at = frappe.utils.now_datetime()
            f.commit_error = None
            job.append("output_documents", {
                "output_doctype": out.doctype, "output_docname": out.name,
                "based_on_findings": f.finding_no, "created_at": frappe.utils.now_datetime(),
                "created_by": frappe.session.user, "status": "Draft",
                "amount": _extract_amount(doc_dict),
            })
            created += 1
        except Exception as e:
            f.committed = 0
            f.commit_error = str(e)[:500]
            failed += 1
            frappe.log_error(frappe.get_traceback(), f"AIO commit {job.name} {f.finding_no}")
    return {"created": created, "failed": failed, "status": "Committed"}


def _commit_grouped(job, atype, retry_only):
    """Gộp mọi finding Approved/Modified → 1 Journal Entry tổng (dự phòng TT48).

    1 dòng Nợ 6426 tổng, nhiều dòng Có 2293 chi tiết theo từng khách hàng.
    """
    targets = [f for f in job.findings
               if f.review_status in ("Approved", "Modified") and not f.committed]
    if not targets:
        return {"created": 0, "failed": 0, "status": "Committed"}

    expense_acc, provision_acc = _resolve_provision_accounts(job.company)
    if not expense_acc or not provision_acc:
        for f in targets:
            f.commit_error = f"Không tìm thấy TK dự phòng ({TT200_ACCOUNTS['doubtful_expense']}/{TT200_ACCOUNTS['doubtful_provision']}) cho công ty {job.company}. Cấu hình trong AI Office Settings."
        return {"created": 0, "failed": len(targets), "status": "Committed"}

    total = 0.0
    credit_rows = []
    for f in targets:
        p = json.loads(f.final_payload or f.suggested_payload or "{}")
        amt = float(p.get("provision_amount") or 0)
        if amt <= 0:
            continue
        total += amt
        credit_rows.append({
            "account": provision_acc,
            "credit_in_account_currency": amt,
            "user_remark": f"Dự phòng {p.get('invoice')} — KH {p.get('customer')} ({f.compliance_reference})",
        })

    try:
        je = frappe.get_doc({
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": job.company,
            "posting_date": frappe.utils.nowdate(),
            "user_remark": f"Trích lập dự phòng nợ khó đòi TT48 — AIO Job {job.name}",
            "accounts": [
                {"account": expense_acc, "debit_in_account_currency": total},
                *credit_rows,
            ],
        })
        je.insert()
        now = frappe.utils.now_datetime()
        for f in targets:
            f.committed = 1
            f.committed_doctype = "Journal Entry"
            f.committed_docname = je.name
            f.committed_at = now
            f.commit_error = None
        job.append("output_documents", {
            "output_doctype": "Journal Entry", "output_docname": je.name,
            "based_on_findings": ",".join(f.finding_no for f in targets),
            "created_at": now, "created_by": frappe.session.user,
            "status": "Draft", "amount": total,
        })
        return {"created": 1, "failed": 0, "status": "Committed"}
    except Exception as e:
        for f in targets:
            f.commit_error = str(e)[:500]
        frappe.log_error(frappe.get_traceback(), f"AIO commit grouped {job.name}")
        return {"created": 0, "failed": len(targets), "status": "Committed"}


def _resolve_account(company, account_number):
    """Tìm tên Account theo số hiệu TK + company (CoA TT200 từ erpnextvn)."""
    return frappe.db.get_value(
        "Account", {"account_number": account_number, "company": company}, "name"
    )


def _resolve_provision_accounts(company):
    """TK dự phòng cho TT48: ưu tiên override trong Settings, fallback số hiệu TK TT200."""
    s = frappe.get_cached_doc("AI Office Settings")
    expense = s.default_provision_expense_account or _resolve_account(company, TT200_ACCOUNTS["doubtful_expense"])
    provision = s.default_provision_account or _resolve_account(company, TT200_ACCOUNTS["doubtful_provision"])
    # nếu override thuộc company khác thì bỏ qua (an toàn)
    if expense and frappe.db.get_value("Account", expense, "company") != company:
        expense = _resolve_account(company, TT200_ACCOUNTS["doubtful_expense"])
    if provision and frappe.db.get_value("Account", provision, "company") != company:
        provision = _resolve_account(company, TT200_ACCOUNTS["doubtful_provision"])
    return expense, provision


def _render_mapping(jinja_src, payload, job):
    rendered = Template(jinja_src).render(p=payload, job=job)
    return json.loads(rendered)


def _extract_amount(doc_dict):
    if doc_dict.get("accounts"):
        return sum(float(a.get("debit_in_account_currency") or 0) for a in doc_dict["accounts"])
    if doc_dict.get("difference_amount"):
        return float(doc_dict["difference_amount"])
    return 0

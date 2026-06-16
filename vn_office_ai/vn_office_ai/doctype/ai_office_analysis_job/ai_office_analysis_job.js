// Client Script — AI Office Analysis Job (Tier 2 review UI).
// CSS class prefix `aio-` để tránh xung đột Bootstrap của ERPNext.

frappe.ui.form.on("AI Office Analysis Job", {
    refresh(frm) {
        render_action_buttons(frm);
        render_progress(frm);
        render_review_summary(frm);
    },
});

function render_action_buttons(frm) {
    if (frm.is_new()) return;
    const st = frm.doc.status;

    // Chạy phân tích
    if (frm.doc.docstatus === 0 && ["Draft", "Failed"].includes(st)) {
        frm.add_custom_button(__("Chạy phân tích"), () => {
            frappe.call({
                method: "vn_office_ai.api.analysis.run",
                args: { job_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Đang khởi động phân tích..."),
                callback: () => frm.reload_doc(),
            });
        }).addClass("btn-primary");
    }

    // Duyệt nhanh (bulk) khi đang review
    if (frm.doc.docstatus === 0 && ["Ready For Review", "Under Review"].includes(st)) {
        frm.add_custom_button(__("Duyệt tất cả Info"), () => {
            bulk_review(frm, "Approved", "Info");
        }, __("Duyệt nhanh"));
        frm.add_custom_button(__("Từ chối tất cả còn lại"), () => {
            bulk_review(frm, "Rejected", null);
        }, __("Duyệt nhanh"));
    }

    // Commit
    if (frm.doc.docstatus === 0 && st === "Ready To Commit") {
        frm.add_custom_button(__("Commit (tạo chứng từ nháp)"), () => {
            frappe.confirm(
                __("Tạo chứng từ nháp từ {0} đề xuất đã duyệt?", [frm.doc.approved_findings + frm.doc.modified_findings]),
                () => {
                    frappe.call({
                        method: "vn_office_ai.api.analysis.commit",
                        args: { job_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Đang tạo chứng từ..."),
                        callback: (r) => {
                            frm.reload_doc();
                            frappe.msgprint(__("Đã tạo {0} chứng từ, lỗi {1}.",
                                [r.message.created, r.message.failed]));
                        },
                    });
                }
            );
        }).addClass("btn-primary");
    }

    // Retry commit khi có lỗi
    if (frm.doc.docstatus === 0 && st === "Committed") {
        const has_error = (frm.doc.findings || []).some(
            (f) => ["Approved", "Modified"].includes(f.review_status) && !f.committed);
        if (has_error) {
            frm.add_custom_button(__("Thử lại commit lỗi"), () => {
                frappe.call({
                    method: "vn_office_ai.api.analysis.retry_commit",
                    args: { job_name: frm.doc.name },
                    freeze: true,
                    callback: (r) => {
                        frm.reload_doc();
                        frappe.msgprint(__("Tạo thêm {0}, còn lỗi {1}.",
                            [r.message.created, r.message.failed]));
                    },
                });
            });
        }
    }
}

function bulk_review(frm, decision, severity) {
    frappe.call({
        method: "vn_office_ai.api.analysis.bulk_review",
        args: { job_name: frm.doc.name, decision: decision, severity: severity },
        freeze: true,
        callback: (r) => {
            frm.reload_doc();
            frappe.show_alert({ message: __("Đã duyệt {0} đề xuất", [r.message.reviewed]), indicator: "green" });
        },
    });
}

function render_progress(frm) {
    if (frm.doc.status === "Analyzing") {
        frm.dashboard.set_headline(__("Đang phân tích..."));
        if (!frm._aio_realtime_bound) {
            frm._aio_realtime_bound = true;
            frappe.realtime.on("aio_analysis_progress", (d) => {
                if (d.job === frm.doc.name) {
                    frm.dashboard.set_headline(
                        __("Đang phân tích chunk {0}/{1}", [d.chunk, d.total]));
                }
            });
        }
    }
    if (frm.doc.status === "Failed" && frm.doc.error_message) {
        frm.dashboard.set_headline(
            `<span class="aio-error-hint">Lỗi: ${frappe.utils.escape_html(frm.doc.error_message)}</span>`);
    }
}

function render_review_summary(frm) {
    if (!frm.doc.total_findings) return;
    const d = frm.doc;
    const html = `
        <div class="aio-review-summary">
            <b>Tiến độ duyệt:</b>
            <span class="aio-pill">Tổng: ${d.total_findings}</span>
            <span class="aio-pill aio-pending">Chờ: ${d.pending_findings}</span>
            <span class="aio-pill aio-approved">Duyệt: ${d.approved_findings}</span>
            <span class="aio-pill aio-rejected">Từ chối: ${d.rejected_findings}</span>
            ${d.critical_findings ? `<span class="aio-pill aio-critical">⚠️ Critical: ${d.critical_findings}</span>` : ""}
        </div>`;
    frm.dashboard.add_section(html);
}

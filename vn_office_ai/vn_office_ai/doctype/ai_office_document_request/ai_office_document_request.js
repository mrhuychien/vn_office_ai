// Client Script cho AI Office Document Request
// Quy ước: mọi class CSS custom đều prefix `aio-` để tránh xung đột Bootstrap của ERPNext.

frappe.ui.form.on("AI Office Document Request", {
    onload(frm) {
        frm.set_query("source_docname", () => {
            let filters = {};
            if (frm._source_filter) {
                try { filters = JSON.parse(frm._source_filter); } catch (e) {}
            }
            return { filters };
        });
    },

    refresh(frm) {
        render_preview(frm);
        render_generate_buttons(frm);
        render_error_hint(frm);
    },

    template(frm) {
        if (!frm.doc.template) return;
        // tải schema câu hỏi + source_filter của template
        frappe.db.get_doc("AI Office Template", frm.doc.template).then((tpl) => {
            frm._source_filter = tpl.source_filter || "";
            build_question_rows(frm, tpl.questions || []);
        });
    },

    source_docname(frm) {
        if (frm.doc.source_docname && frm.doc.template && !frm.is_new()) {
            frappe.call({
                method: "vn_office_ai.api.document.prefill_from_source",
                args: { request_name: frm.doc.name, source_docname: frm.doc.source_docname },
                callback: () => frm.reload_doc(),
            });
        }
    },
});

// ───────────────────────── helpers ─────────────────────────

function build_question_rows(frm, questions) {
    const existing = {};
    (frm.doc.field_values || []).forEach((fv) => (existing[fv.field_name] = fv));

    frm.clear_table("field_values");
    questions.forEach((q) => {
        const row = frm.add_child("field_values");
        row.field_name = q.field_name;
        row.field_label = q.question_label;
        row.field_type = q.field_type;
        if (existing[q.field_name]) {
            row.value_text = existing[q.field_name].value_text;
            row.source_of_value = existing[q.field_name].source_of_value;
        } else if (q.default_value) {
            row.value_text = q.default_value;
            row.source_of_value = "Default";
        } else {
            row.source_of_value = "User Input";
        }
    });
    frm.refresh_field("field_values");
}

function render_preview(frm) {
    const f = frm.get_field("preview_html");
    if (!f) return;
    if (frm.doc.status === "Generated" && frm.doc.preview_html) {
        f.$wrapper.html(`<div class="aio-doc-preview">${frm.doc.preview_html}</div>`);
    } else {
        f.$wrapper.html(
            `<div class="aio-doc-preview aio-empty">Chưa có bản xem trước. ` +
            `Điền thông tin rồi bấm "Tạo bản xem trước".</div>`
        );
    }
}

function render_generate_buttons(frm) {
    if (frm.doc.docstatus !== 0 || frm.is_new()) return;
    if (["Ready to Generate", "Failed", "Asking Questions"].includes(frm.doc.status)) {
        frm.add_custom_button(__("Tạo bản xem trước"), () => {
            frappe.call({
                method: "vn_office_ai.api.document.generate",
                args: { request_name: frm.doc.name },
                freeze: true,
                freeze_message: __("AI đang soạn tài liệu..."),
                callback: () => frm.reload_doc(),
            });
        }).addClass("btn-primary");
    }
    if (frm.doc.status === "Generated") {
        frm.add_custom_button(__("Tạo lại"), () => {
            frappe.call({
                method: "vn_office_ai.api.document.generate",
                args: { request_name: frm.doc.name, regenerate: 1 },
                freeze: true,
                freeze_message: __("Đang tạo lại..."),
                callback: () => frm.reload_doc(),
            });
        });
    }
}

function render_error_hint(frm) {
    if (frm.doc.status === "Failed" && frm.doc.error_message) {
        frm.dashboard.set_headline(
            `<span class="aio-error-hint">Lỗi: ${frappe.utils.escape_html(frm.doc.error_message)}</span>`
        );
    }
}

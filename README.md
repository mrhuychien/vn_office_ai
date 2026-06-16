# VN Office AI

AI văn phòng cho doanh nghiệp Việt — soạn tài liệu & phân tích kế toán **native trên ERPNext v16**.

Lấy cảm hứng từ các sản phẩm "trợ lý kế toán AI", nhưng khác biệt cốt lõi: thay vì xuất file Word rời rạc phải nhập tay lại, `vn_office_ai` đọc thẳng dữ liệu trong ERPNext (Employee, Sales Invoice, GL Entry, Stock Ledger) và — với nghiệp vụ phân tích — tạo ra **chứng từ nháp submittable** (Journal Entry, Stock Reconciliation) để kế toán duyệt.

## Hai tầng

**Tier 1 — Tạo tài liệu nhanh** (Phase 1 ✅)
Chọn template → điền form hội thoại (tự prefill từ record nguồn) → AI soạn → xuất `.docx`/PDF → đính kèm vào record nguồn. 14 template: HĐLĐ, Phiếu thu/chi, Bảng lương, Phiếu nhập/xuất kho, Quyết định, Biên bản họp, Công văn...

**Tier 2 — AI Analyst** (Phase 3 — sắp tới)
Upload dữ liệu hoặc query nội bộ → AI phân tích → đề xuất từng dòng → kế toán duyệt từng đề xuất (review gate bằng permlevel) → commit thành JE/Stock Recon nháp. 8 nghiệp vụ: đối chiếu ngân hàng, cân kho, dự phòng nợ khó đòi TT48/2019, bút toán điều chỉnh cuối kỳ, đánh giá tỷ giá, quyết toán TNCN...

## Triết lý: Bạn quyết định, AI thực hiện

AI không bao giờ tự ghi sổ. Mọi đề xuất tài chính đều ở trạng thái nháp (docstatus 0) chờ người có quyền duyệt. Tier 2 enforce điều này ở tầng database (permlevel), không phải chỉ ở giao diện.

## Yêu cầu

- Frappe v16 + ERPNext v16
- `erpnextvn` (bản địa hoá VN: CoA TT200/TT133, thuế VN) — khuyến nghị
- OpenRouter API key (bạn tự cung cấp — app không host LLM, không tính phí AI)
- Python: `python-docx`, `beautifulsoup4` (cài tự động qua pip khi bench setup)

## Cài đặt

```bash
cd frappe-bench
bench get-app vn_office_ai <git-url>
bench --site <site> install-app vn_office_ai
bench --site <site> migrate
bench build --app vn_office_ai
bench restart
```

Sau khi cài: vào **AI Office Settings** → nhập OpenRouter API Key → chọn model.

## Cấu hình LLM

| Trường | Mặc định | Ghi chú |
|---|---|---|
| Default Model (Tier 1) | `google/gemini-2.5-flash` | Soạn tài liệu — nhanh, rẻ |
| Analyst Model (Tier 2) | `anthropic/claude-sonnet-4.7` | Phân tích — cần structured output |
| Che PII trước khi gửi LLM | Bật | Che CCCD/MST/STK/SĐT trong văn bản tự do |

## Roles

- **AI Office User** — soạn văn bản nội bộ (Biên bản họp, Công văn, Thông báo)
- **AI Office Analyst** — chạy AI Analyst job (không duyệt finding)
- **AI Office Manager** — duyệt finding, quản lý template/analysis type

## Trạng thái phát triển

- [x] **Phase 1** — Foundation + Tier 1 (Document Gen): Settings, Template, Document Request, OpenRouter, PII mask
- [x] **Phase 2** — 14 template đầy đủ + 4 Print Format (Phiếu thu/chi/nhập/xuất kho) + Workspace dashboard
- [x] **Phase 3** — Tier 2 AI Analyst: Analysis Type/Job/Finding/Input/Output, review gate permlevel, background runner, commit → JE/Stock Recon draft
- [x] **Phase 4** — 8 loại phân tích (đối chiếu NH, cân kho, dự phòng TT48, làm lại sổ, kiểm tra chi phí TNDN, kết chuyển cuối kỳ, đánh giá tỷ giá, quyết toán TNCN), cấu hình TK, hardening (SQL guard, role check, PII)
- [ ] **Tiếp theo** — viết test (FrappeTestCase) qua `nextcode-qa`; security audit chính thức qua `nextcode-security`; publish marketplace

## Nội dung

**14 template Tier 1:** HĐLĐ xác định thời hạn, Phiếu thu, Phiếu chi, Quyết định bổ nhiệm, Biên bản họp, Bảng thanh toán lương, Phiếu nhập kho, Phiếu xuất kho, Hợp đồng kinh tế, Biên bản giao nhận, Biên bản thanh lý TSCĐ, Báo cáo chi phí công tác, Thông báo, Công văn.

**8 loại phân tích Tier 2:**
| Mã | Nghiệp vụ | Output |
|---|---|---|
| ANL-BANK-RECON | Đối chiếu ngân hàng | Journal Entry (mỗi giao dịch) |
| ANL-STOCK-COUNT | Cân kho / kiểm kê | Stock Reconciliation |
| ANL-DEBT-PROV | Dự phòng nợ khó đòi TT48/2019 | Journal Entry (gộp 1 bút toán) |
| ANL-REBUILD-LEDGER | Làm lại sổ từ chứng từ thô | Journal Entry (mỗi nghiệp vụ) |
| ANL-TNDN-EXPENSE | Kiểm tra chi phí trước quyết toán TNDN | Báo cáo (Report Only) |
| ANL-PERIOD-CLOSE | Bút toán kết chuyển cuối kỳ | Journal Entry |
| ANL-FX-REVAL | Đánh giá lại tỷ giá ngoại tệ | Journal Entry |
| ANL-PIT-SETTLE | Quyết toán thuế TNCN | Báo cáo (Report Only) |

Mọi output ở trạng thái **nháp (docstatus 0)**. Kế toán kiểm tra và tự ghi sổ (submit).

## License

MIT

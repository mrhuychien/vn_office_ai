# INVESTIGATION — `bench install-app vn_office_ai` vỡ ở `sync_fixtures`

## Triệu chứng
Cài app thất bại giữa chừng:

```
An error occurred while installing vn_office_ai:
Cannot edit Standard Notification. To edit, please disable this and duplicate it
frappe.exceptions.ValidationError
```

Traceback dừng ở `frappe/utils/fixtures.py → import_fixtures` khi import
`vn_office_ai/fixtures/notification.json`, record `AIO Job Ready For Review`.

## Root cause (1 câu)
5 Notification trong `fixtures/notification.json` mang `is_standard: 1`; Frappe
`Notification.validate_standard()` **throw** với mọi notification `is_standard=1`
+ `enabled=1` khi `developer_mode` tắt, và — khác Print Format — **không có
exemption `in_install`/`in_migrate`**, nên bước `sync_fixtures` của `install-app`
(chạy validate đầy đủ vì `data_import=True`) vỡ trên site production.

## Evidence (giả thuyết → bằng chứng)

### H1 — Throw đến từ `is_standard`, không phải nội dung notification
`frappe/email/doctype/notification/notification.py` (version-16):
```python
def validate_standard(self):
    if self.is_standard and self.enabled and not frappe.conf.developer_mode:
        frappe.throw(_("Cannot edit Standard Notification. To edit, please disable this and duplicate it"))
```
→ Điều kiện throw = `is_standard AND enabled AND not developer_mode`. Không có
cờ `in_install`/`in_migrate`/`in_import` nào được miễn. Site dev của tác giả bật
`developer_mode` nên lưu được is_standard=1; site cài production thì không. **Xác nhận.**

### H2 — Tại sao fixtures vỡ mà "standard module record" thì không
`frappe/modules/import_file.py → import_doc(...)`:
```python
if not data_import:
    doc.flags.ignore_validate = True   # bỏ qua validate()
    ...
doc.insert()
```
- Fixtures sync gọi `import_file_by_path(..., data_import=True)` → **validate() chạy** → throw.
- Standard module-record sync (`sync_for` lúc migrate/install) dùng mặc định
  `data_import=False` → `ignore_validate=True` → **validate() bị bỏ qua** → không throw.
→ Đó là lý do ERPNext ship được standard notification (qua module record), còn ship
qua `fixtures` thì chết. **Xác nhận.**

### H3 — Print Format `standard: "Yes"` có vỡ tiếp không? KHÔNG
`frappe/printing/doctype/print_format/print_format.py`:
```python
if (self.standard == "Yes"
    and not frappe.local.conf.get("developer_mode")
    and not frappe.flags.in_migrate
    and not frappe.flags.in_install      # ← có exemption
    and not frappe.in_test):
    frappe.throw(_("Standard Print Format cannot be updated"))
```
`installer.py` đặt `frappe.flags.in_install = name` (dòng 276/289) và chỉ reset ở
dòng 348 — tức **vẫn còn set** lúc `sync_fixtures(name)` (dòng 339). Nên Print Format
`standard: "Yes"` được miễn → an toàn khi install lẫn migrate. **Xác nhận.**

### H4 — Quét toàn bộ cùng lớp (không vá lẻ)
- `is_standard: 1`: chỉ `fixtures/notification.json` (5 record).
- `standard: "Yes"`: `fixtures/print_format.json` (4 record) — an toàn (H3).
- Không có fixture Dashboard / Dashboard Chart / Number Card (lớp "no in_install
  exemption" còn lại).
→ `notification.json` là file **duy nhất** thuộc lớp lỗi này.

## Reproduction
1. Site với `developer_mode = 0` (production mặc định).
2. `bench --site <site> install-app vn_office_ai`.
3. Banner after_install in ra (chạy trước sync_fixtures), rồi vỡ ở `notification.json`
   record đầu (`AIO Job Ready For Review`).

## Fix
`fixtures/notification.json`: đổi `is_standard` của cả 5 record từ `1` → `0`.
Notification vẫn `enabled: 1`, vẫn bắn đúng event (`Value Change` trên `status`) và
gửi system notification như cũ — chỉ khác là không bị khoá "standard" (admin có thể
sửa; migrate sẽ ghi đè lại từ fixtures, đúng hành vi fixtures bình thường).

Thêm comment cảnh báo trong `hooks.py` cạnh fixture `Notification` để lần re-export
sau không vô tình đưa `is_standard=1` trở lại.

### Vì sao chọn cách này (không chuyển sang module record)
App ship đồng nhất theo hướng `fixtures`. Print Format `standard: "Yes"` cũng ship qua
fixtures và chạy được (nhờ exemption `in_install`). Với Notification, do thiếu exemption,
cách tối thiểu & idempotent là `is_standard=0`. Muốn notification "khoá standard" thật
thì phải bỏ `Notification` khỏi hook `fixtures` và đặt làm module record ở
`vn_office_ai/vn_office_ai/notification/<name>/<name>.json` (+ file message sidecar) —
nhiều bề mặt hơn, lợi ích (khoá sửa) không đáng cho app này.

## Rollback
Một file fixture + một comment. Hoàn tác: `git revert <commit>` hoặc đặt lại
`is_standard: 1` (sẽ tái hiện lỗi install trên site production).

## Regression guard
- Comment inline trong `hooks.py` (đã thêm).
- Kiểm tra tĩnh trước khi commit fixtures:
  ```bash
  python3 -c "import json,sys; d=json.load(open('vn_office_ai/fixtures/notification.json')); \
  bad=[n['name'] for n in d if n.get('is_standard')]; \
  sys.exit('FAIL is_standard=1: '+', '.join(bad)) if bad else print('OK')"
  ```
- Sau khi sửa: **bắt buộc** cài lại trên site SẠCH (`drop-site` + `new-site` rồi
  `install-app`) — không `install-app --force` lên site bẩn (che mất bug).

---

# Domino 2 — `workspace.json` thiếu reqd `type` (parent Workspace)

## Triệu chứng (sau khi fix notification.json)
Install qua được notification.json + print_format.json, chết ở file fixture **cuối**
(`workspace.json`):
```
frappe.exceptions.MandatoryError: [Workspace, VN Office AI]: type
missing = [('type', 'Error: Value missing for Workspace: Type')]
d = Workspace Link (h8gdd9o1bj)
```

## Root cause (1 câu)
Workspace (parent) trong Frappe v16 có field **`type`** (Select `Workspace/Link/URL`,
`default="Workspace"`, **`reqd=1`**); fixture không có `type`, và **fixtures không áp
default** nên `_validate_mandatory` báo thiếu → install vỡ.

## Evidence
- `desk/doctype/workspace/workspace.json` (v16): field `type` `reqd:1`, `default:"Workspace"`.
- Bẫy biến vòng lặp (đúng như playbook B1): traceback in `d = Workspace Link (...)`
  nhưng đó chỉ là biến lặp cuối frame. Tin format `[doctype, name]: field` →
  **parent `Workspace VN Office AI` thiếu `type`**, KHÔNG phải child Workspace Link.
- Sweep tĩnh parent + 8 `links` + 5 `shortcuts` vs schema thật v16 → chỉ **parent.type**
  thiếu; mọi child đủ reqd.

## Fix
`fixtures/workspace.json`: thêm `"type": "Workspace"` vào parent. (workspace.json là
fixture cuối theo alphabet → hết domino, install chạy trọn.)

## Rollback
Xoá dòng `"type": "Workspace"` → tái hiện MandatoryError.

## Regression guard (chạy trước khi commit fixtures)
```bash
python3 - <<'PY'
import json
ws=json.load(open('vn_office_ai/fixtures/workspace.json'))[0]
assert ws.get('type'), "Workspace parent thiếu reqd 'type'"
print('OK workspace.type =', ws['type'])
PY
```

## Bài học chung (cả 2 domino)
Fixtures import chạy **validate đầy đủ** (`data_import=True`) và **không áp field
default**. Mọi reqd field phải ghi tường minh trong JSON; mọi doctype có guard
`is_standard`/standard không-exempt-install (Notification, Dashboard, Chart) không
được ship `is_standard=1` qua fixtures.

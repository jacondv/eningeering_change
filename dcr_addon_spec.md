# TÀI LIỆU MÔ TẢ ĐẦY ĐỦ ADDON — Engineering Change / DCR Management (Odoo 19)

> Đây là tài liệu mô tả **toàn bộ** addon (Functional + Technical Specification), dùng làm input duy nhất cho Claude Code build trọn bộ module từ đầu đến cuối. Tài liệu gồm: mục tiêu, phạm vi, vai trò người dùng, toàn bộ data model, toàn bộ workflow, toàn bộ màn hình/view, bảo mật, thông báo, báo cáo, và cấu trúc code hoàn chỉnh.

---

## MỤC LỤC

1. Giới thiệu & Mục tiêu
2. Phạm vi (Scope)
3. Vai trò người dùng (Actors & Roles)
4. Kiến trúc module & cấu trúc thư mục
5. Toàn bộ Data Model (chi tiết từng field, từng model)
6. Workflow / State Machine đầy đủ
7. Ma trận quyền (Security Matrix) đầy đủ
8. Toàn bộ màn hình (Views) & Menu
9. Thông báo (Notification / Email / Activity)
10. Báo cáo in (PDF Report)
11. Ràng buộc nghiệp vụ (Business Rules & Validations)
12. Yêu cầu phi chức năng (Non-functional Requirements)
13. Manifest & thứ tự load file
14. Kịch bản test chấp nhận (UAT scenarios)
15. Lộ trình triển khai (Roadmap)
16. Phụ lục: Glossary

---
## Importance note
Only allow change code in addons folder. Do not change the original odoo code

## 1. Giới thiệu & Mục tiêu

Addon **`engineering_change`** quản lý toàn bộ vòng đời của một **Yêu cầu thay đổi kỹ thuật** (Engineering Change Request) trong doanh nghiệp sản xuất/kỹ thuật, gồm 2 loại:

- **Minor Change**: thay đổi nhỏ, chỉ cần Manager duyệt.
- **DCR – Design Change Request**: thay đổi lớn, cần thêm BOD (Ban lãnh đạo) duyệt.

Mục tiêu addon:
- Số hoá toàn bộ quy trình đề xuất → đánh giá rủi ro → duyệt → triển khai → nghiệm thu bằng chứng, thay thế quy trình giấy/email rời rạc.
- Lưu vết đầy đủ (audit trail) phục vụ tuân thủ ISO/IATF.
- Dễ dùng: giao diện trực quan (Kanban, statusbar, badge màu), dễ quản lý: phân quyền rõ ràng, có nhắc hạn tự động, có báo cáo tổng hợp.

- UI and notifications are all in English.
---

## 2. Phạm vi (Scope)

**Trong phạm vi (In-scope):**
- Tạo/quản lý Request (Minor Change & DCR).
- Đính kèm hình ảnh, bản vẽ liên quan (link hoặc file).
- Đánh giá rủi ro (RPN nhập tay + các trường ảnh hưởng).
- Luồng duyệt 2 cấp: Manager → (nếu DCR) BOD.
- BOD review có comment tập thể, duyệt 1 lần (không tuần tự).
- Giao Action/Task khi Implement, theo dõi deadline & trạng thái. Có nhiều task cho 1 Request
- Upload Evidence (bằng chứng hoàn thành) cho từng Action, có mô tả.
- Followers & thông báo email tự động (dùng `mail.thread`).
- Phân quyền 4 nhóm: General User, Engineer, BOD, Manager/Admin.

**Ngoài phạm vi (Out-of-scope, ghi chú cho tương lai):**
- Portal cho khách hàng/đối tác bên ngoài xem DCR — để giai đoạn 2.
- Tích hợp ERP khác (MES, PLM) — không có trong bản này  — để giai đoạn 2..
- Chữ ký điện tử (e-signature) trên PDF report — chỉ để placeholder chữ ký .
- Đa cấp duyệt BOD (multi-level approval) — theo yêu cầu gốc chỉ cần 1 approval.

---

## 3. Vai trò người dùng (Actors & Roles)

| Role | Mô tả | Quyền chính |
|---|---|---|
| **General User** | Nhân viên thông thường, có thể là Implement Member | Xem (read-only) các request mình liên quan; nếu là Assignee của Action thì được upload Evidence cho Action đó |
| **Engineer** | Người tạo và theo dõi Request kỹ thuật | Tạo/sửa/submit request của mình; xem toàn bộ tab; không xoá |
| **Engineering Manager** | Duyệt DCR, comment, assign Action | Xem tất cả DCR đang ở BOD Review; approve/reject; assign Action; xem toàn bộ dữ liệu |
| **BOD (Ban lãnh đạo)** | Duyệt DCR, comment | Xem tất cả DCR đang ở BOD Review; approve/reject; assign Action; xem toàn bộ dữ liệu |
| **Admin** | Quản trị hệ thống, duyệt cấp 1 | Full access: duyệt Minor/DCR cấp 1, cấu hình sequence, xem/sửa/xoá tất cả |

Một user có thể thuộc nhiều group (kế thừa): `Manager ⊃ BOD`, `Engineer ⊃ General User`.

---

## 4. Kiến trúc module & cấu trúc thư mục

```
engineering_change/
├── __init__.py
├── __manifest__.py
├── security/
│   ├── engineering_change_groups.xml       # 4 groups + category
│   ├── engineering_change_rules.xml        # record rules
│   └── ir.model.access.csv                 # ACL cho tất cả model
├── data/
│   ├── ir_sequence_data.xml                # sequence Request No & DCR No
│   ├── mail_template_data.xml              # 6 email template (mục 9)
│   └── ir_cron_data.xml                    # cron nhắc overdue
├── models/
│   ├── __init__.py
│   ├── engineering_change.py               # model chính
│   ├── engineering_change_image.py
│   ├── engineering_change_document.py
│   ├── engineering_change_action.py
│   └── engineering_change_action_evidence.py
├── wizard/
│   ├── __init__.py
│   ├── engineering_change_reject_wizard.py
│   └── engineering_change_reject_wizard_views.xml
├── views/
│   ├── engineering_change_views.xml        # form/list/kanban/search chính
│   ├── engineering_change_action_views.xml
│   └── engineering_change_menus.xml
├── report/
│   ├── engineering_change_report.xml       # ir.actions.report
│   └── engineering_change_report_templates.xml  # QWeb template
├── static/
│   ├── description/icon.png
│   └── src/scss/engineering_change.scss     # style badge RPN, decoration
└── tests/
    ├── __init__.py
    └── test_engineering_change.py           # unit test workflow + security
```

---

## 5. Toàn bộ Data Model

### 5.1 `engineering.change` (model trung tâm)

Kế thừa: `mail.thread`, `mail.activity.mixin`
`_order = "create_date desc"`
`_description = "Engineering Change Request"`

| # | Field | Type | Required | Default | Ghi chú |
|---|---|---|---|---|---|
| 1 | `name` | Char | readonly | `'New'` | Request No, sinh qua `ir.sequence` khi Submit. Format `YYMM-xxx` |
| 2 | `request_type` | Selection(`minor`,`dcr`) | required | `minor` | |
| 3 | `dcr_no` | Char | readonly | `False` | Chỉ có giá trị nếu `request_type='dcr'`; sinh khi Manager approve. Format `YYYYDCxxx` |
| 4 | `title` | Char | required | | |
| 5 | `description` | Html | required | | |
| 6 | `engineer_id` | Many2one(`res.users`) | required | current user | |
| 7 | `create_date` | Datetime | auto | | field chuẩn Odoo |
| 8 | `close_date` | Datetime | readonly | | set khi state → done |
| 9 | `state` | Selection (5 giá trị, mục 6) | | `draft` | `tracking=True` |
| 10 | `company_id` | Many2one(`res.company`) | | current company | |
| 11 | `active` | Boolean | | `True` | |
| 12 | `image_ids` | One2many → `engineering.change.image` | | | |
| 13 | `document_ids` | One2many → `engineering.change.document` | | | |
| 14 | `action_ids` | One2many → `engineering.change.action` | | | |
| 15 | `implement_team_ids` | Many2many(`res.users`) | | `[engineer_id]` | |
| 16 | `implement_owner_id` | Many2one(`res.users`) | | | phải ∈ `implement_team_ids` |
| 17 | `rpn` | Integer | required trước khi Submit | `0` | |
| 18 | `rpn_level` | Selection compute (`low`,`medium`,`high`) | | | store=True để filter/group |
| 19 | `impact_lead_time` | Text | | | |
| 20 | `impact_safety` | Text | | | |
| 21 | `impact_compliance` | Text | | | |
| 22 | `bod_approver_id` | Many2one(`res.users`) readonly | | | |
| 23 | `reject_reason` | Text readonly | | | ghi từ wizard reject |
| 24 | `action_count` | Integer compute | | | |
| 25 | `action_done_count` | Integer compute | | | |
| 26 | `progress` | Float compute (%) | | | |
| 27 | `has_overdue_action` | Boolean compute store=True | | | dùng cho decoration-danger trên list |
| 28 | `message_follower_ids`, `message_ids`, `activity_ids` | (tự động từ mail.thread/mail.activity.mixin) | | | Followers, Chatter, Activities |

**Compute methods:**
```python
@api.depends('rpn')
def _compute_rpn_level(self):
    for rec in self:
        if rec.rpn >= 71:
            rec.rpn_level = 'high'
        elif rec.rpn >= 30:
            rec.rpn_level = 'medium'
        else:
            rec.rpn_level = 'low'

@api.depends('action_ids.status')
def _compute_action_stats(self):
    for rec in self:
        rec.action_count = len(rec.action_ids)
        rec.action_done_count = len(rec.action_ids.filtered(lambda a: a.status == 'done'))
        rec.progress = (rec.action_done_count / rec.action_count * 100) if rec.action_count else 0.0

@api.depends('action_ids.is_overdue')
def _compute_has_overdue(self):
    for rec in self:
        rec.has_overdue_action = any(rec.action_ids.mapped('is_overdue'))
```

---

### 5.2 `engineering.change.image`
`_description = "Engineering Change Image"`

| Field | Type | Required |
|---|---|---|
| `change_id` | Many2one(`engineering.change`, ondelete='cascade') | required |
| `image` | Image (binary, `max_width=1920, max_height=1920`) | required |
| `caption` | Char | |

UI: One2many hiển thị dạng **Kanban nhỏ** (ảnh thumbnail + caption), có nút mở popup xem full size (dùng widget `image` với `options="{'preview_image': 'image'}"`).

---

### 5.3 `engineering.change.document`
`_description = "Engineering Change Related Drawing/Document"`

| Field | Type | Required |
|---|---|---|
| `change_id` | Many2one(`engineering.change`, ondelete='cascade') | required |
| `name` | Char | required |
| `doc_type` | Selection(`link`,`file`) | required, default `file` |
| `link` | Char | required nếu `doc_type='link'` |
| `attachment` | Binary | required nếu `doc_type='file'` |
| `attachment_filename` | Char | |

Specific Business Logic & UI/UX Behaviors:
   - Dynamic Visibility: In the XML view, the 'link' field should only be visible when doc_type is 'link'. The 'attachment' field should only be visible when doc_type is 'file'.
   - Auto-populate 'name' from File: When a user uploads a file into the 'attachment' field, the system must automatically extract the filename and fill it into the 'name' field if it is currently empty.
   - Special Behavior for 'link' type: Even when doc_type is set to 'link', the UI should still provide a button/widget to open the local file explorer. When the user selects a local file, instead of uploading the binary file, the system should automatically copy the absolute/relative file path of that file and paste it into the 'link' field (and optionally set the 'name' field based on the filename).

UI: List view, click on the file name to open the link (target `_blank`) or load the attachment.

---

### 5.4 `engineering.change.action`
`_description = "Engineering Change Action/Task"`, `_order = "deadline asc"`

| Field | Type | Required |
|---|---|---|
| `change_id` | Many2one(`engineering.change`, ondelete='cascade') | required |
| `name` | Char (Task Name) | required |
| `description` | Text (Technical Description) | |
| `assignee_id` | Many2one(`res.users`) | required |
| `manager_id` | Many2one(`res.users`) | default = `change_id.bod_approver_id` hoặc creator |
| `deadline` | Date | |
| `status` | Selection(`draft`,`in_progress`,`done`,`cancel`) | default `draft` |
| `evidence_ids` | One2many → `engineering.change.action.evidence` | |
| `evidence_count` | Integer compute | |
| `is_overdue` | Boolean compute store=True | `deadline < today and status not in (done, cancel)` |

When `status` changes to `done` for the first time → automatically create `mail.activity` done or post a message to the parent `change_id` chatter("Action X completed by Y").

---

### 5.5 `engineering.change.action.evidence`
`_description = "Engineering Change Action Evidence"`

| Field | Type | Required |
|---|---|---|
| `action_id` | Many2one(`engineering.change.action`, ondelete='cascade') | required |
| `attachment` | Binary | required |
| `attachment_filename` | Char | |
| `description` | Char | required — giải thích bằng chứng là gì |
| `upload_uid` | Many2one(`res.users`) readonly, default current user | |
| `upload_date` | Datetime readonly, default now | |

---

### 5.6 Wizard `engineering.change.reject.wizard` (TransientModel)

Dùng chung cho cả Engineering Manager reject và BOD reject.

| Field | Type |
|---|---|
| `change_id` | Many2one(`engineering.change`) |
| `reject_reason` | Text, required |
| `reject_by` | Selection(`manager`,`bod`) — set ngầm khi mở wizard từ nút tương ứng |

Method `action_confirm_reject()`: ghi `reject_reason` vào `change_id`, set `state='draft'`, `message_post` thông báo Engineer, đóng wizard.

---

## 6. Workflow / State Machine đầy đủ

### 6.1 Sơ đồ trạng thái

```
                         ┌─────────────────────────────────────────┐
                         │                                         │
   [draft] --Submit--> [waiting_manager_approval]                  │
                              │        │                           │
                     Approve  │        │ Reject (wizard)           │
                     (minor)  │        └──────────────> [Cancel]◄──┤
                              │                                    │
                              ▼                                    │
                         [implement] ◄── Approve(DCR) ── [bod_review]
                              │                                │
                       Tất cả Action                    Reject(wizard)
                       done / Manager                          │
                       bấm Close                                ▼
                              │                              [Cancel]
                              ▼
                          [done] --Reopen (Manager)--> [implement]
```

### 6.2 Bảng chuyển trạng thái chi tiết

| Từ | Sự kiện | Điều kiện | Đến | Side-effect |
|---|---|---|---|---|
| `draft` | `action_submit()` | title, description, rpn > 0 đều có | `waiting_manager_approval` | Sinh `name` (Request No) nếu là `'New'`; post chatter; notify group Manager |
| `waiting_manager_approval` | `action_manager_approve()` | request_type = minor | `implement` | notify `implement_team_ids` |
| `waiting_manager_approval` | `action_manager_approve()` | request_type = dcr | `bod_review` | notify group BOD |
| `waiting_manager_approval` | mở wizard reject → confirm | | `draft` | ghi `reject_reason`; notify `engineer_id` |
| `waiting_manager_approval` | Manager đổi `request_type` | trước khi approve | (không đổi state) | cho phép sửa type ngay tại bước này theo yêu cầu gốc |
| `bod_review` | `action_bod_approve()` | `implement_team_ids` không rỗng | `implement` | set `bod_approver_id = uid`; sinh `dcr_no` nếu chưa có; notify `implement_team_ids` |
| `bod_review` | mở wizard reject → confirm | | `draft` | ghi `reject_reason`; notify `engineer_id` |
| `implement` | tự động (compute trigger) hoặc `action_close_request()` | `action_done_count == action_count` và `action_count > 0`, hoặc Manager bấm Close thủ công | `done` | set `close_date = now()` |
| `done` | `action_reopen()` | chỉ Manager | `implement` | clear `close_date` |

### 6.3 Nút bấm hiển thị theo state (invisible logic)

| State | Nút hiển thị | Nhóm được thấy |
|---|---|---|
| draft | Submit | Engineer (owner), Engineering Manager |
| waiting_manager_approval | Approve, Reject | group_ec_manager |
| bod_review | Approve, Reject | group_ec_bod |
| implement | Close Request | group_ec_manager |
| done | Reopen | group_ec_manager |

Statusbar field `state` hiển thị trên header form với `statusbar_visible="draft,waiting_manager_approval,bod_review,implement,done"`.

---

## 7. Ma trận quyền (Security Matrix) đầy đủ

### 7.1 ACL theo model (Read/Write/Create/Unlink)

| Model | General User | Engineer | BOD | Manager |
|---|---|---|---|---|
| `engineering.change` | R | RWC | RW | RWCD |
| `engineering.change.image` | R | RWC | RW | RWCD |
| `engineering.change.document` | R | RWC | RW | RWCD |
| `engineering.change.action` | R | RW (chỉ status nếu là assignee — xem 7.3) | RWC | RWCD |
| `engineering.change.action.evidence` | R (chỉ của mình) / C nếu là assignee | RWC | RWC | RWCD |
| `engineering.change.reject.wizard` | – | – | RWC | RWC |

### 7.2 Record Rules

| Rule | Model | Domain | Áp dụng group |
|---|---|---|---|
| `ec_change_rule_user` | engineering.change | request mà user là `engineer_id`, `implement_team_ids`, follower, hoặc `create_uid` | group_ec_user |
| `ec_change_rule_engineer` | engineering.change | request do chính mình tạo (`create_uid = uid`) — hoặc mở rộng xem tất cả nếu doanh nghiệp muốn Engineer thấy nhau, cấu hình được | group_ec_engineer |
| `ec_change_rule_bod_manager` | engineering.change | `[(1,'=',1)]` (toàn quyền xem) | group_ec_bod, group_ec_manager |
| `ec_evidence_rule_assignee` | engineering.change.action.evidence | `action_id.assignee_id = uid` | group_ec_user, group_ec_engineer |

### 7.3 Ràng buộc field-level (không phải ACL model mà là logic Python)

- Field `status` của `engineering.change.action`: General User (Assignee) **chỉ được** đổi status (`draft→in_progress→done`), không được sửa `name`, `deadline`, `manager_id`. Thực hiện bằng `write()` override kiểm tra `self.env.user` không thuộc group Engineer/BOD/Manager thì chỉ cho phép thay đổi key `status` và `evidence_ids`.

```python
def write(self, vals):
    if not self.env.user.has_group('engineering_change.group_ec_engineer') \
       and not self.env.user.has_group('engineering_change.group_ec_bod'):
        allowed_keys = {'status', 'evidence_ids'}
        if set(vals.keys()) - allowed_keys:
            raise AccessError(_("You can only update the Status and Proof."))
    return super().write(vals)
```

---

## 8. Toàn bộ màn hình (Views) & Menu

### 8.1 Menu tree

```
Engineering Change (menu gốc)
├── My Requests            (action: domain engineer_id = uid)
├── All Requests           (action: full list, chỉ Manager/BOD thấy menu này)
├── Waiting Approval    (action: domain state phù hợp group hiện tại)
├── Actions / Tasks        (action list riêng cho engineering.change.action, filter assignee_id = uid mặc định)
└── Configuration          (chỉ Manager)
    ├── Sequences
    └── Groups/Users
```

### 8.2 Form view `engineering.change` — bố cục chi tiết

```
┌─────────────────────────────────────────────────────────┐
│ [Statusbar: Draft | Waiting Manager | BOD Review | Implement | Done] │
│ Buttons: Submit / Approve / Reject / Close / Reopen       │
│ Stat buttons (góc phải header): [Actions: n] [Evidence: n] [Progress: n%] │
├─────────────────────────────────────────────────────────┤
│ Request No: 2601-012      DCR No: 2026DC001 (nếu có)      │
│ Title: ______________________________                    │
│ Request Type: (radio Minor/DCR)                           │
│ Engineer: [user]     Created: [date]     Closed: [date]   │
├─────────────────────────────────────────────────────────┤
│ Description (rich text)                                   │
├─────────────────────────────────────────────────────────┤
│ TABS:                                                      │
│  [General Info] [Images] [Related Drawings]                │
│  [Risk Assessment] [Implement Team] [Actions]               │
├─────────────────────────────────────────────────────────┤
│ Chatter (mail.thread widget): Followers, Log, Send message │
└─────────────────────────────────────────────────────────┘
```

- Tab **Images**: kanban ảnh + caption, nút thêm ảnh, nút view fullsize.
- Tab **Related Drawings**: list editable, cột Name/Type/Link hoặc File. Mặc định là Link
- Tab **Risk Assessment**: RPN (hiển thị kèm badge màu theo `rpn_level`), 3 ô Text lớn (Lead time / Safety / Compliance impact).
- Tab **Implement Team**: many2many tags widget cho `implement_team_ids`, field `implement_owner_id` (domain giới hạn trong implement_team_ids).
- Tab **Actions**: list editable bottom, cột Name/Assignee/Manager/Deadline/Status (badge màu theo status, decoration-danger nếu `is_overdue`), mở dòng để thấy sub-tab Evidence bên trong form Action (Many2one popup hoặc list nested).

### 8.3 List view

Cột: Request No, Title, Type (badge), Engineer, State (badge), RPN (badge màu), Deadline gần nhất của Action con, decoration-danger toàn dòng nếu `has_overdue_action = True`.

### 8.4 Kanban view

Group by `state`; card gồm Title, avatar Engineer, RPN badge, progress bar (`progressbar` widget dùng `progress` field), nhãn Type.

### 8.5 Search view

- Filters: My Requests, DCR Only, Minor Only, Overdue Actions, Waiting Approval, Closed.
- Group By: State, Request Type, Engineer, Month (create_date), RPN Level.

### 8.6 Action list view (`engineering.change.action`)

Menu riêng "Actions/Tasks" cho phép Assignee xem nhanh việc của mình toàn hệ thống (cross-request), filter mặc định `assignee_id = uid`, group by `status`.

---

## 9. Thông báo (Notification / Email / Activity)

| # | Sự kiện | Người nhận | Kênh | Template |
|---|---|---|---|---|
| 1 | Submit | group Manager | mail.thread message + email | `mail_template_submit` |
| 2 | Manager Reject | Engineer | email + chatter | `mail_template_manager_reject` |
| 3 | Manager Approve (DCR) | group BOD | email + chatter | `mail_template_bod_review` |
| 4 | Manager Approve (Minor) | Implement Team | email | `mail_template_implement` |
| 5 | BOD comment | tất cả follower (BOD khác) | chatter (tự động qua mail.thread) | (không cần template riêng) |
| 6 | BOD Reject | Engineer | email + chatter | `mail_template_bod_reject` |
| 7 | BOD Approve | Implement Team | email | `mail_template_implement` (dùng lại) |
| 8 | Action mới được assign | Assignee | `mail.activity` (due_date = deadline) | Activity type "To Do" |
| 9 | Action quá hạn (cron hàng ngày) | Assignee + Manager | email | `mail_template_overdue` |
| 10 | Request Close | Engineer + Implement Team | chatter | (message_post đơn giản) |

Cron: `ir.cron` "EC: Check Overdue Actions", chạy mỗi ngày 07:00, gọi `model._cron_check_overdue()`.

---

## 10. Báo cáo in (PDF Report) — QWeb

Action report `action_report_engineering_change` gắn vào nút Print trên form.

Nội dung PDF:
- Header: Logo công ty, Request No, DCR No (nếu có), ngày in.
- General Information (đầy đủ field).
- Risk Assessment (RPN + 3 impact field).
- Danh sách Images (thumbnail).
- Danh sách Related Drawings.
- Danh sách Actions kèm trạng thái & deadline.
- Khung chữ ký placeholder: Engineer / Manager / BOD Approver.

---

## 11. Ràng buộc nghiệp vụ (Business Rules & Validations)

1. Không Submit nếu thiếu `title`, `description`, hoặc `rpn <= 0`.
2. Không BOD Approve nếu `implement_team_ids` rỗng.
3. `implement_owner_id` phải thuộc `implement_team_ids` (constrain).
4. `dcr_no` chỉ sinh 1 lần duy nhất (không sinh lại nếu đã có).
5. Action `deadline` không được nhỏ hơn ngày hiện tại khi tạo mới (cảnh báo, không chặn cứng — cho phép override vì có thể nhập hồi tố).
6. 
7. Request chỉ tự động chuyển `done` khi có ít nhất 1 Action và tất cả đều `done`; nếu không có Action nào, Manager phải bấm Close thủ công (tránh auto-close nhầm).
8. Không cho xoá (`unlink`) Request nếu `state != draft` (chỉ Manager mới override được nếu thật sự cần, qua context đặc biệt — mặc định chặn).

---

## 12. Yêu cầu phi chức năng (Non-functional Requirements)

- Tương thích Odoo 19 Community/Enterprise (không dùng field/widget chỉ có ở Enterprise).
- Đa ngôn ngữ: chuẩn bị `_()` cho toàn bộ string, sẵn sàng export `.pot`. Ngôn ngữ mặc định hiện tại là English
- Đa công ty (multi-company) qua `company_id`.
- Hiệu năng: index cho `state`, `engineer_id`, `dcr_no` (dùng `index=True` trên field quan trọng).
- Không hardcode ID phòng ban/user — toàn bộ qua group/config.

---

## 13. Manifest & thứ tự load file

```python
{
    'name': 'Engineering Change / DCR Management',
    'version': '19.0.1.0.0',
    'category': 'Manufacturing/Quality',
    'summary': 'Quản lý yêu cầu thay đổi kỹ thuật (Minor Change & DCR)',
    'depends': ['base', 'mail', 'web'],
    'data': [
        'security/engineering_change_groups.xml',
        'security/engineering_change_rules.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'wizard/engineering_change_reject_wizard_views.xml',
        'views/engineering_change_views.xml',
        'views/engineering_change_action_views.xml',
        'views/engineering_change_menus.xml',
        'report/engineering_change_report.xml',
        'report/engineering_change_report_templates.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
```
> Thứ tự bắt buộc: **security groups → rules → ACL → data (sequence/template/cron) → wizard views → main views → menus → report**. Menu phải load sau action/view mà nó tham chiếu.

---

## 14. Kịch bản test chấp nhận (UAT) tối thiểu

1. Engineer tạo request, để trống RPN, bấm Submit → phải báo lỗi.
2. Engineer tạo request minor change đầy đủ thông tin → Submit → Manager thấy trong "Waiting Approval" → Approve → state = Implement, Implement Team nhận email.
3. Engineer tạo DCR → Submit → Manager Approve → state = BOD Review, tất cả BOD nhận email → 1 BOD Approve → state = Implement, `dcr_no` được sinh.
4. BOD Reject kèm lý do → state = Draft, Engineer nhận email có lý do.
5. Manager assign 3 Action cho 3 Assignee khác nhau, mỗi Assignee chỉ thấy/sửa được Action + Evidence của chính mình (test bằng user General User).
6. Đặt deadline Action về quá khứ, chưa Complete → chạy cron thủ công → email nhắc được gửi, dòng hiển thị màu đỏ trong list.
7. Hoàn thành hết Action → Request tự chuyển `done`, `close_date` được set.
8. General User không thuộc group nào cố mở Request không liên quan → bị chặn (record rule).

---

## 15. Lộ trình triển khai (Roadmap)

| Sprint | Nội dung |
|---|---|
| 1 | Model chính + state machine + sequence + ACL + form/list/search cơ bản |
| 2 | Images, Documents, Risk Assessment, Implement Team |
| 3 | BOD Review flow, reject wizard, mail templates |
| 4 | Action & Evidence, stat buttons, mail.activity |
| 5 | Record rules đầy đủ + field-level restriction cho Assignee |
| 6 | Kanban view, decoration, cron overdue, dashboard filters |
| 7 (optional) | QWeb PDF report, Portal access mở rộng |

---

## 16. Phụ lục: Glossary

| Thuật ngữ | Giải thích |
|---|---|
| DCR | Design Change Request — yêu cầu thay đổi thiết kế, cần BOD duyệt |
| RPN | Risk Priority Number — chỉ số ưu tiên rủi ro, nhập tay |
| BOD | Board of Directors — nhóm duyệt cấp cao |
| Implement Team | Nhóm thực thi thay đổi sau khi được duyệt |
| Evidence | Bằng chứng/tài liệu chứng minh Action đã hoàn thành |

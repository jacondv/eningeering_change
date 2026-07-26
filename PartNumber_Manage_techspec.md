# Tech Spec: Part Number Management Addon

## 1. Mục tiêu

Xây dựng addon Odoo quản lý part number của công ty, độc lập với `product.product`/`product.template` nhưng có khả năng liên kết sang đó khi cần mua bán/tồn kho. Addon cần hỗ trợ:

- Sinh `part_number` tự động theo Material Group, lấp khoảng trống (gap-filling), không cho nhập tay
- Mapping N-N giữa mã cũ và mã mới trong quá trình chuyển đổi định dạng mã
- Quản lý part được build từ BOM, với thuộc tính động tùy theo loại part (chưa biết trước schema)
- Trang nhập liệu chuyên dụng (OWL) gộp chung luồng "Tạo mới" và "Chuyển đổi mã cũ", có preview số trước khi lưu, và cơ chế lưu từng dòng độc lập (partial success + retry)

## 2. Quyết định kiến trúc chính

### 2.1. Không kế thừa trực tiếp `product.product` / `product.template`

**Lý do:**
- `state` nghiệp vụ (draft/active/obsolete) khác hoàn toàn với field `active` (boolean) của Odoo.
- Long/short description theo nghiệp vụ riêng, không cần gánh theo toàn bộ field thương mại (giá, thuế, kế toán) bắt buộc trên `product.product`.
- Vendor ở đây đơn giản là 1-1 hoặc field tham chiếu, không cần độ phức tạp của `product.supplierinfo`.

**Khi cần link:** chỉ tạo `product.product` và gán vào field `product_id` khi part đó thực sự cần mua/bán/tồn kho. Không bắt buộc mọi part number đều phải có product tương ứng.

### 2.2. Mapping mã cũ/mã mới: bảng trung gian, không dùng field cố định

- Không dùng field `code_type` (new/legacy) vì vai trò cũ/mới không phải thuộc tính cố định của 1 record — trong chuỗi chuyển đổi nhiều lần (A → B → C), mã B vừa là "mới" (so với A) vừa là "cũ" (so với C).
- Dùng bảng mapping riêng (`part_number_mapping`) với 2 Many2one trỏ về chính model part number → vai trò cũ/mới xác định theo từng cặp quan hệ, không phải nhãn toàn cục.
- Hỗ trợ đúng nghĩa N-N: 1 mã mới có thể gộp nhiều mã cũ, và 1 mã cũ có thể tách thành nhiều mã mới.
- Format mã không dùng để phân biệt cũ/mới (mã cũ đôi khi cũng là 8 ký tự) → không validate theo độ dài chuỗi.

### 2.3. Thuộc tính động cho part BOM-built: mô hình EAV

- Vài chục loại BOM (`part_type`), mỗi loại có tập thuộc tính riêng, không biết trước schema đầy đủ → không thể hard-code field (Float/Char) cho từng thuộc tính.
- Dùng mô hình EAV, tương tự cách Odoo tự thiết kế `product.attribute`: `part_type` định nghĩa attribute nào áp dụng, `part_attribute` định nghĩa thuộc tính, `part_attribute_value` lưu giá trị thực tế gán cho từng part.
- Thêm attribute mới không cần sửa code/migrate DB, chỉ cần tạo record qua UI.

### 2.4. Sinh `part_number` tự động, lấp khoảng trống, không cho nhập tay

**Quy tắc sinh mã:** `part_number` = 8 ký tự số = `material_group.code` (4 ký tự) + `suffix` (4 ký tự). Suffix luôn là giá trị nhỏ nhất còn trống trong group đó (kể cả các số đã bị bỏ do record bị xóa hẳn — số đó tự động "trống trở lại", không cần xử lý gì thêm vì suffix luôn tính lại từ dữ liệu hiện có tại thời điểm generate).

**Ví dụ:** Material Group `1207`, đã tồn tại `12070001` và `12070004` → mã tiếp theo lần lượt là `12070000`, `12070002`, `12070003`.

**`part_number` là field readonly**, không cho người dùng gõ tay. Chỉ được điền thông qua nút **Generate** — cả ở dạng preview (xem trước, không ghi DB) lẫn khi Save thật (tính lại và ghi DB, có lock).

**Race condition khi nhiều người tạo part cùng lúc:** dùng `pg_advisory_xact_lock(material_group_id)` khi tính suffix thật lúc Save. Lock này chỉ khóa theo từng `material_group_id` cụ thể — 2 người tạo part ở 2 group khác nhau không ảnh hưởng nhau; chỉ khi trùng đúng 1 group mới phải chờ nhau trong thời gian rất ngắn (1 transaction). Với vài chục material group và ~20 nhân sự, xác suất và mức độ ảnh hưởng là chấp nhận được.

**Preview ≠ số thật cuối cùng.** Preview (`preview_next_suffix`) chỉ đọc dữ liệu hiện tại, không lock, không ghi — dùng để hiển thị gợi ý trên UI. Khi Save thật, server luôn tính lại suffix từ đầu (có lock), không tin vào giá trị đã preview trước đó, vì giữa 2 thời điểm có thể đã có người khác Save trước.

**Toàn bộ việc tính toán này chạy ở server, không tính ở client (OWL).** Trình duyệt không có quyền truy vấn DB và dữ liệu client luôn có nguy cơ cũ ngay khi vừa load — vì vậy OWL chỉ gọi RPC lên server và hiển thị kết quả trả về, không tự suy luận số tiếp theo.

**Cảnh báo, không chặn**, nếu `part_number` không khớp định dạng `material_group.code + sequence_suffix` (trường hợp hiếm, ví dụ do sửa dữ liệu trực tiếp trong DB) — dùng `_logger.warning`, không `raise ValidationError`.

## 3. Data Model

### 3.1. `your_module.part_number` (bảng chính)

| Field | Kiểu | Ghi chú |
|---|---|---|
| `part_number` | Char, index, copy=False, **readonly** | Sinh tự động qua nút Generate, không nhập tay |
| `material_group_id` | Many2one `material_group`, required | |
| `sequence_suffix` | Char(4), copy=False, readonly | 4 ký tự cuối, tách riêng để dễ tính toán |
| `job_number` | Many2one `project.project` | **Required khi tạo mới qua UI**; bỏ qua khi import Excel (dùng context `skip_job_number_check`) |
| `short_description` | Char | |
| `long_description` | Text | |
| `state` | Selection: draft / active / obsolete | default draft, tracking=True |
| `vendor_id` | Many2one `res.partner` | |
| `vendor_ref` | Char | Mã tham chiếu phía vendor |
| `part_type_id` | Many2one `part_type` | Chỉ set khi part là BOM-built |
| `bom_id` | Many2one `mrp.bom` | Chỉ set khi part là BOM-built |
| `product_id` | Many2one `product.product` | Optional, chỉ set khi cần mua bán/tồn kho |
| `attribute_value_ids` | One2many `part_attribute_value.part_id` | Thuộc tính động (BOM-built) |
| `superseded_ids` | One2many `part_number_mapping.new_part_id` | Các mã cũ mà part này thay thế |
| `supersedes_ids` | One2many `part_number_mapping.legacy_part_id` | Các mã mới đã thay thế part này |
| `replacement_display` (computed, store) | Char | Text gộp mã thay thế, phục vụ search/list view |
| `create_date` | Datetime (built-in Odoo) | Tự có sẵn, không cần khai báo — thời gian tạo |
| `create_uid` | Many2one `res.users` (built-in Odoo) | Tự có sẵn, không cần khai báo — người tạo |

**SQL constraint:** `unique(part_number)` — đây là lưới chặn cuối cùng chống trùng, kể cả khi advisory lock đã giảm gần hết rủi ro.

### 3.2. `your_module.part_number_mapping`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `new_part_id` | Many2one `part_number`, required | ondelete=cascade |
| `legacy_part_id` | Many2one `part_number`, required | ondelete=cascade |

**SQL constraint:** `unique(new_part_id, legacy_part_id)`

### 3.3. `your_module.material_group`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `code` | Char(4), required, index | Ví dụ "1207" |
| `description` | Char, required | Mô tả nhóm, ví dụ "Bearing & Bushing" |

**SQL constraint:** `unique(code)`. `name_get` hiển thị dạng `"1207 - Bearing & Bushing"` khi chọn Many2one.

### 3.4. `your_module.part_type`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `name` | Char, required | Tên loại BOM, ví dụ "Bearing Assembly" |
| `attribute_ids` | Many2many `part_attribute` | Thuộc tính áp dụng cho loại này |

### 3.5. `your_module.part_attribute`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `name` | Char, required | "Length", "Width", "Material"... |
| `value_type` | Selection: float / char / selection | default char |
| `uom` | Char | Đơn vị, ví dụ "mm", "kg" |
| `option_ids` | One2many `part_attribute_option.attribute_id` | Chỉ dùng khi value_type = selection |

### 3.6. `your_module.part_attribute_option`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `attribute_id` | Many2one `part_attribute`, required | |
| `name` | Char, required | Ví dụ "S", "M", "L" |

### 3.7. `your_module.part_attribute_value`

| Field | Kiểu | Ghi chú |
|---|---|---|
| `part_id` | Many2one `part_number`, required | ondelete=cascade |
| `attribute_id` | Many2one `part_attribute`, required | |
| `value_float` | Float | Dùng khi value_type = float |
| `value_char` | Char | Dùng khi value_type = char |
| `value_option_id` | Many2one `part_attribute_option` | Dùng khi value_type = selection |
| `display_value` (computed, store) | Char | Giá trị hiển thị gộp theo value_type |

## 4. Sơ đồ quan hệ

```
part_type (1) ──< attribute_ids >── (n) part_attribute (1) ──< option_ids >── (n) part_attribute_option
                                            │
                                            │ (n)
                                            ▼
part_number (1) ──< attribute_value_ids >── (n) part_attribute_value
     │  │
     │  ├── material_group_id ──> material_group  (định nghĩa 4 ký tự đầu)
     │  ├── job_number ──> project.project (required khi tạo mới qua UI)
     │  ├── bom_id ──> mrp.bom
     │  └── product_id ──> product.product (optional link)
     │
     └── part_number_mapping (new_part_id / legacy_part_id, cả 2 đều trỏ về part_number)
          → cho phép N-N giữa mã cũ và mã mới
```

## 5. Logic nghiệp vụ chính (backend)

### 5.1. Sinh suffix — lấp khoảng trống, có lock khi ghi thật

```python
@api.model
def _get_next_suffix(self, material_group_id):
    """Tính suffix thật, dùng khi SAVE. Có advisory lock theo material_group_id
    để tránh 2 transaction tính trùng suffix khi tạo cùng lúc trong cùng group."""
    self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", (material_group_id,))
    existing = self.search([
        ('material_group_id', '=', material_group_id)
    ]).mapped('sequence_suffix')
    used = set(int(s) for s in existing if s)
    for i in range(10000):
        if i not in used:
            return f'{i:04d}'
    raise UserError('Material Group này đã dùng hết 10.000 mã (0000-9999)!')

@api.model
def preview_next_suffix(self, material_group_id):
    """Chỉ xem trước, KHÔNG lock, KHÔNG ghi. Dùng cho nút Generate (preview)
    trên OWL UI. Kết quả có thể lệch so với số thật lúc Save nếu có người
    khác tạo part cùng group trong lúc đó — điều này chấp nhận được."""
    if not material_group_id:
        return False
    existing = self.search([
        ('material_group_id', '=', material_group_id)
    ]).mapped('sequence_suffix')
    used = set(int(s) for s in existing if s)
    for i in range(10000):
        if i not in used:
            return f'{i:04d}'
    return False
```

Vì suffix luôn tính lại từ `search()` tại thời điểm gọi, khi 1 record bị xóa hẳn, suffix của nó tự động "trống trở lại" — không cần xử lý gì thêm.

### 5.2. Tạo hàng loạt, xử lý từng dòng độc lập (partial success + retry)

Đây là entry point duy nhất mà OWL gọi khi bấm Save (dùng chung cho cả luồng "Tạo mới" và "Chuyển đổi mã cũ" — phân biệt qua có/không có `conversion_legacy_id` trong từng dòng payload):

```python
@api.model
def create_batch_with_generated_number(self, vals_list):
    """Nhận danh sách part cần tạo (mới hoặc convert). Mỗi dòng chạy trong
    1 savepoint riêng: dòng nào lỗi (ví dụ trùng part_number do va chạm hiếm
    gặp) thì rollback đúng dòng đó, KHÔNG ảnh hưởng các dòng đã thành công
    trong cùng batch. Trả về kết quả từng dòng để client biết dòng nào cần
    generate + save lại."""
    results = []
    for idx, vals in enumerate(vals_list):
        result = {'index': idx, 'success': False, 'part_id': None,
                   'error': None, 'part_number': None}
        try:
            with self.env.cr.savepoint():
                if not vals.get('job_number'):
                    raise UserError('Job Number là bắt buộc.')
                if not vals.get('material_group_id'):
                    raise UserError('Material Group là bắt buộc.')

                suffix = self._get_next_suffix(vals['material_group_id'])
                group = self.env['your_module.material_group'].browse(
                    vals['material_group_id'])

                attribute_values = vals.pop('attribute_values', [])
                conversion_legacy_id = vals.pop('conversion_legacy_id', None)

                vals['sequence_suffix'] = suffix
                vals['part_number'] = f"{group.code}{suffix}"

                part = self.create(vals)

                for av in attribute_values:
                    if av.get('value'):
                        self.env['your_module.part_attribute_value'].create({
                            'part_id': part.id,
                            'attribute_id': av['attribute_id'],
                            'value_char': av['value'],
                        })

                # Luồng convert: tạo mapping + chuyển state mã cũ, cùng savepoint
                if conversion_legacy_id:
                    self.env['your_module.part_number_mapping'].create({
                        'new_part_id': part.id,
                        'legacy_part_id': conversion_legacy_id,
                    })
                    self.browse(conversion_legacy_id).state = 'obsolete'

                result['success'] = True
                result['part_id'] = part.id
                result['part_number'] = part.part_number

        except Exception as e:
            result['error'] = str(e)
            _logger.warning('Part creation failed for row %s: %s', idx, e)

        results.append(result)

    return results
```

### 5.3. Bắt buộc `job_number` khi tạo mới qua UI, bỏ qua khi import

```python
@api.model_create_multi
def create(self, vals_list):
    is_import = self.env.context.get('skip_job_number_check')
    if not is_import:
        for vals in vals_list:
            if not vals.get('job_number'):
                raise UserError('Job Number là bắt buộc khi tạo part mới.')
    return super().create(vals_list)
```

Script import Excel gọi kèm context: `.with_context(skip_job_number_check=True).create(vals_list)`.

### 5.4. Chặn chuyển sang `active` nếu chưa có `part_number`

```python
@api.constrains('state', 'part_number')
def _check_active_requires_part_number(self):
    for rec in self:
        if rec.state == 'active' and not rec.part_number:
            raise ValidationError('Part chưa có Part Number, cần Generate trước khi Active.')
```

### 5.5. Hiển thị mã thay thế khi tra cứu mã cũ

`replacement_display` (computed, store) gộp tất cả `new_part_id.part_number` từ `supersedes_ids`, hiển thị ngay trên form/list view khi tra cứu mã cũ.

## 6. Frontend Architecture (OWL)

### 6.1. Vì sao dùng OWL thay vì form view + wizard chuẩn

- Cần điều phối nhiều bước liền mạch: chọn Material Group → xem preview số → nhập attribute động theo Part Type → validate chéo → Save — mượt hơn nhiều so với rời rạc qua nhiều nút/wizard riêng lẻ.
- Cần verify dữ liệu real-time (RPC) trước khi dữ liệu thực sự chạm DB.
- Gộp chung 1 trang cho cả 2 luồng "Tạo mới" và "Chuyển đổi mã cũ" bằng tab, chia sẻ chung logic Save/Generate/partial-retry.

**Trade-off:** tốn công phát triển hơn form/wizard có sẵn (tự viết CSS, loading state, test JS), và cần maintain riêng qua các version Odoo do OWL API có thể đổi giữa major version.

### 6.2. Cấu trúc thư mục

```
your_module/
├── static/src/
│   ├── js/
│   │   └── part_management_page/
│   │       ├── part_management_page.js
│   │       ├── part_management_page.xml
│   │       └── part_management_page.scss
├── views/
│   └── actions.xml
├── models/
│   └── part_number.py
```

### 6.3. Client action

```xml
<record id="action_part_management_page" model="ir.actions.client">
    <field name="name">Quản lý Part Number</field>
    <field name="tag">part_management_page</field>
</record>

<menuitem id="menu_part_management" name="Quản lý Part Number"
          action="action_part_management_page" parent="menu_part_number_root"/>
```

### 6.4. Nguyên tắc quan trọng: mọi tính toán part_number chạy ở SERVER

Client (OWL) **không tự tính** suffix hay part_number dưới bất kỳ hình thức nào — kể cả để preview. Lý do:

- Trình duyệt không có quyền truy vấn DB.
- Dữ liệu ở client (nếu có load sẵn) luôn có nguy cơ cũ ngay khi vừa load — người khác có thể vừa tạo part khác trong lúc đó.

→ Nút **Generate** trên từng dòng chỉ gọi RPC `preview_next_suffix` (đọc DB thật, không lock, không ghi), hiển thị kết quả trả về. Khi Save thật, server tính lại từ đầu qua `_get_next_suffix` (có lock) — **không dùng lại** giá trị đã preview mà client gửi lên.

### 6.5. Component chính — gộp tab Tạo mới / Chuyển đổi, preview, partial-retry

```javascript
/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class PartManagementPage extends Component {
    static template = "your_module.PartManagementPage";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            activeTab: "create",  // "create" | "convert"
            rows: [],
            errors: {},
            isSaving: false,
        });

        onWillStart(async () => {
            this.materialGroups = await this.orm.searchRead(
                "your_module.material_group", [], ["code", "description"]
            );
            this.jobNumbers = await this.orm.searchRead("project.project", [], ["name"]);
        });
    }

    switchTab(tab) {
        this.state.activeTab = tab;
    }

    addRow() {
        this.state.rows.push({
            _localId: Date.now() + Math.random(),
            material_group_id: false,
            job_number: false,
            short_description: "",
            part_type_id: false,
            attributes: [],
            conversion_legacy_id: this.state.activeTab === "convert" ? false : null,
            previewPartNumber: null,
            status: "pending",   // pending | success | error
            resultPartNumber: null,
            errorMessage: null,
        });
    }

    removeRow(localId) {
        this.state.rows = this.state.rows.filter(r => r._localId !== localId);
    }

    // Chỉ hỏi server để hiển thị gợi ý — không tính gì ở client
    async onGenerateClick(row) {
        if (!row.material_group_id) {
            this.notification.add("Vui lòng chọn Material Group trước", { type: "warning" });
            return;
        }
        row.isGenerating = true;
        try {
            const previewSuffix = await this.orm.call(
                "your_module.part_number", "preview_next_suffix", [row.material_group_id]
            );
            const group = this.materialGroups.find(g => g.id === row.material_group_id);
            row.previewPartNumber = group.code + previewSuffix;
        } finally {
            row.isGenerating = false;
        }
    }

    validateClientSide() {
        const errors = {};
        for (const row of this.state.rows) {
            if (row.status === "success") continue;
            if (!row.material_group_id) errors[`${row._localId}_group`] = "Bắt buộc";
            if (!row.job_number) errors[`${row._localId}_job`] = "Bắt buộc";
            if (this.state.activeTab === "convert" && !row.conversion_legacy_id) {
                errors[`${row._localId}_legacy`] = "Cần chọn mã cũ để convert";
            }
        }
        this.state.errors = errors;
        return Object.keys(errors).length === 0;
    }

    // Chỉ gửi lên server những dòng CHƯA thành công — dòng success giữ nguyên,
    // không gửi lại để tránh tạo trùng khi bấm Save nhiều lần.
    async onSaveClick() {
        if (!this.validateClientSide()) {
            this.notification.add("Vui lòng kiểm tra các dòng bị lỗi", { type: "danger" });
            return;
        }

        const pendingRows = this.state.rows.filter(r => r.status !== "success");
        if (pendingRows.length === 0) {
            this.notification.add("Không có dòng nào cần lưu", { type: "info" });
            return;
        }

        this.state.isSaving = true;
        try {
            const payload = pendingRows.map(row => ({
                material_group_id: row.material_group_id,
                job_number: row.job_number,
                short_description: row.short_description,
                part_type_id: row.part_type_id,
                attribute_values: row.attributes.map(a => ({
                    attribute_id: a.id, value: a.value
                })),
                conversion_legacy_id: row.conversion_legacy_id || null,
            }));

            const results = await this.orm.call(
                "your_module.part_number", "create_batch_with_generated_number", [payload]
            );

            results.forEach((res, i) => {
                const row = pendingRows[i];
                if (res.success) {
                    row.status = "success";
                    row.resultPartNumber = res.part_number;  // số THẬT trả về, không phải preview
                    row.errorMessage = null;
                } else {
                    row.status = "error";
                    row.errorMessage = res.error;
                    // Giữ lại dòng để user Generate + Save lại
                }
            });

            const successCount = results.filter(r => r.success).length;
            const failCount = results.length - successCount;

            if (failCount === 0) {
                this.notification.add(`Đã tạo thành công ${successCount} part.`, { type: "success" });
            } else {
                this.notification.add(
                    `${successCount} part thành công, ${failCount} part lỗi. ` +
                    `Vui lòng kiểm tra và Save lại các dòng còn lỗi.`,
                    { type: "warning" }
                );
            }
        } finally {
            this.state.isSaving = false;
        }
    }
}

registry.category("actions").add("part_management_page", PartManagementPage);
```

### 6.6. Luồng thực tế người dùng trải qua

1. Chọn tab "Tạo mới" hoặc "Chuyển đổi mã cũ", thêm nhiều dòng để nhập liệu.
2. (Tùy chọn) Bấm **Generate** trên từng dòng để xem trước số dự kiến — chỉ mang tính tham khảo.
3. Bấm **Save** — server xử lý từng dòng độc lập (savepoint riêng), trả về kết quả từng dòng.
4. Dòng thành công: hiện số thật, input bị khóa lại, không gửi lại ở lần Save tiếp theo.
5. Dòng lỗi (ví dụ trùng số do va chạm hiếm gặp): giữ nguyên trên UI, người dùng bấm Generate lại (tùy chọn) rồi Save lại — chỉ dòng này được gửi lên.
6. Lặp lại bước 3–5 tới khi tất cả dòng đều thành công.

## 7. Query mẫu

```python
# Từ 1 part mới, tìm tất cả mã cũ liên quan
part = env['your_module.part_number'].browse(new_id)
legacy_codes = part.superseded_ids.mapped('legacy_part_id.part_number')

# Từ 1 mã cũ, tìm tất cả mã mới đã thay thế nó
legacy = env['your_module.part_number'].browse(legacy_id)
new_codes = legacy.supersedes_ids.mapped('new_part_id.part_number')

# Filter part có Length >= 50 (EAV)
env['your_module.part_number'].search([
    ('attribute_value_ids.attribute_id.name', '=', 'Length'),
    ('attribute_value_ids.value_float', '>=', 50),
])
```

## 8. Module dependencies

| Nhu cầu | Module Odoo |
|---|---|
| Base (bắt buộc) | `product` (đã có sẵn qua base) |
| Job Number | `project` |
| Link tồn kho | `stock` |
| Link BOM | `mrp` |
| Link mua hàng | `purchase` |

`depends` trong `__manifest__.py` tối thiểu: `['base', 'project', 'mrp']` (thêm `product`, `stock`, `purchase` nếu dùng field `product_id` liên kết).

## 9. Câu hỏi/điểm chưa chốt (cần xác nhận trước khi code)

1. **`part_type_id` và `bom_id` có bắt buộc đi cùng nhau không** — mỗi part_type ứng với đúng 1 `mrp.bom`, hay 1 part_type có thể áp dụng nhiều BOM khác nhau (theo nhà máy/thời điểm)?
2. Có cần workflow duyệt (approval) khi chuyển đổi mã hay khi tạo part mới không, hay chỉ cần state đơn giản như hiện tại?
3. Quyền truy cập (security/access rights) theo vai trò nào — mọi user đều sửa được part number, hay cần phân quyền theo nhóm (ví dụ chỉ Purchasing được sửa vendor, chỉ Engineering được sửa attribute)?
4. Sau khi `state` đã `active` (đã có part_number), có cần cho phép **regenerate** (cấp số mới, bỏ số cũ) trong trường hợp đặc biệt nào không, hay tuyệt đối không cho sinh lại?
5. Trang OWL "Quản lý Part Number" có cần giới hạn quyền truy cập theo vai trò không (ví dụ chỉ 1 số nhóm được phép tạo part mới)?

## 10. Thứ tự triển khai đề xuất

1. Model `material_group`, `part_number` (core field + state) + logic sinh suffix (`_get_next_suffix`, `preview_next_suffix`)
2. Model `part_number_mapping` + logic mapping N-N
3. Method `create_batch_with_generated_number` (gộp tạo mới + convert, xử lý savepoint từng dòng)
4. Model `part_type`, `part_attribute`, `part_attribute_option`, `part_attribute_value` (EAV cho BOM-built part)
5. Trang OWL `part_management_page` (tab Tạo mới/Chuyển đổi, nút Generate preview, Save với partial-retry)
6. Security (access rights, record rules nếu cần)
7. Liên kết `product_id` (nếu có phần đó trong scope)
8. Script import Excel (dùng context `skip_job_number_check`)

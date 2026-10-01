# Partnumber ↔ Product Integration — Kế hoạch theo hướng C (DRAFT, đang thảo luận)

> Trạng thái: **đã code trên nhánh `feature/pnm-product-link`, đã diễn tập migrate trên bản sao `jacon_plm_0814`, chưa triển khai production** (ngày 2026-10-01).
> Liên quan: [Partnumber_Manager_TechSpec.md](Partnumber_Manager_TechSpec.md)

---

## 1. Mục tiêu

Liên kết Part Number (`part_number_manager.part_number`) với `product.product`.

**Phạm vi hiện tại: chỉ quản lý thông tin.**
- Lưu thông tin nhà cung cấp theo chuẩn Odoo: Vendor, Vendor code, mã đặt hàng, giá, lead time; một Part có thể có nhiều Vendor.
- **Không** tham gia quy trình đặt hàng, bán hàng hay kho. Mọi product do PNM tạo đều có `sale_ok = purchase_ok = False` và `is_storable = False`, nên không xuất hiện khi tạo PO/SO và không phát sinh tồn kho.

**Sau này (mở dần khi cần):**
- Purchase
- Stock
- BOM chuẩn (`mrp.bom`)

Muốn mở chỉ cần sửa quy tắc trong `_sync_product` rồi chạy lại đồng bộ, **không phải đổi cấu trúc**.

Ràng buộc: **không làm Part phụ thuộc vào Product**. Vòng đời của Part (sinh mã, approval, chuyển đổi legacy) vẫn tách khỏi vòng đời của product.

## 2. Các phương án đã cân nhắc

| Phương án | Mô tả | Kết luận |
|---|---|---|
| A. `_inherits` product.product | Mọi Part bắt buộc có 1 product, dùng chung `name` / `default_code` / `active` | Loại: phải tạo 40k product kể cả mã legacy; menu Products lẫn rác; trùng field `active` / `currency_id`; mọi PNM user cần quyền product; migrate rủi ro cao (cột NOT NULL) |
| B. `_inherit = 'product.template'` | Bỏ model Part, đưa hết field vào product | Loại: phải viết lại toàn bộ module và Hose module |
| **C. Part độc lập + Many2one sang product** | Part giữ nguyên; product chỉ được tạo khi cần; đồng bộ 1 chiều Part → Product | **Chọn** |

**Đánh đổi của C:** phải tự viết và bảo trì phần đồng bộ (`_sync_product`); tên và mã tồn tại ở hai nơi. Kiểm soát bằng quy tắc **"Part là nguồn gốc"** và chặn sửa `default_code` từ phía Product.

## 3. Số liệu hiện tại (`jacon_plm_0814`, chỉ đọc, ngày 2026-09-30)

| Chỉ số | Số lượng |
|---|---|
| Tổng Part | 40.088 |
| product.product / product.supplierinfo | 0 / 0 |
| `make_buy`: make / buy / **trống** | 11.645 / 5.660 / **22.783** |
| Buy có Vendor / Buy không Vendor | 1.454 / 4.206 |
| Make nhưng có dữ liệu Vendor (dữ liệu mâu thuẫn) | **69**: 26 có Vendor, 41 chỉ có mã đặt hàng, 2 chỉ có giá |
| Buy nhưng `obsolete` | 50 |
| Có Vendor (tổng) | 1.617, gồm 202 Vendor khác nhau |
| Vendor có Vendor code (`res.partner.ref`) | **0** |
| `vendor_ref` có nhưng không có Vendor | 1.080 |
| Giá có nhưng không có Vendor | 8 |
| `state`: active / obsolete / draft / null / tbd / y | 23.874 / 10.978 / 4.164 / 1.049 / 17 / 6 |
| Mã không chuẩn (legacy) | 10.830 (không mã nào có Vendor) |
| `short_description` trống | 12.767 |
| `part_number` trống | 1 |
| Approval: approved / pending | 40.081 / 7 |

**Module:**
- `product`, `stock`, `purchase`: đã cài
- `mrp`: chưa cài
- `part_number_manager`: cài trên `jacon_plm_0814` và `jacon_plm`

**Addon phụ thuộc:**
- `hose_fitting_manager`: phụ thuộc thật
- `equipment_model`: chỉ nhắc trong comment

## 4. Định nghĩa dữ liệu mua hàng

| Khái niệm | Thuộc về | Lưu ở | Ghi chú |
|---|---|---|---|
| Vendor | Part × Vendor | `product.supplierinfo.partner_id` | Một Part có thể có nhiều Vendor |
| **Vendor code** (mã nhận dạng nhà cung cấp) | Vendor | `res.partner.ref` | Mọi Part của cùng một Vendor dùng chung |
| **Vendor ref** (mã đặt hàng) | Part × Vendor | `product.supplierinfo.product_code` | Khi mở Purchase, Odoo tự in lên dòng PO |
| Price + Currency | Part × Vendor | `supplierinfo.price`, `supplierinfo.currency_id` | Có thể kèm số lượng tối thiểu và thời hạn hiệu lực |
| Lead time | Part × Vendor | `supplierinfo.delay` (ngày) | Part hiện lưu tuần → ×7 |

Lợi ích:
- Hiện tại: một Part có nhiều Vendor; dữ liệu lưu đúng chuẩn Odoo.
- Khi mở Purchase sau này: Odoo tự điền Vendor, giá và mã đặt hàng lên PO, không phải chuyển dữ liệu lần nữa.
- Không bị trùng tên field `currency_id` như ở phương án A.

## 5. Phân biệt Part thiết kế và Part mua

- Vẫn **một model**, phân biệt bằng `make_buy`.
- Thêm hai menu/action:
  - **Design Parts:** `make_buy = 'make'`
  - **Purchased Parts:** `make_buy = 'buy'`
- Menu "All Part Numbers" giữ nguyên.
- Nhóm field Purchase (Vendor, Vendor code, Vendor ref, Price, Lead time) chỉ hiện khi `make_buy != 'make'`. Part có `make_buy` trống vẫn thấy, để không giấu dữ liệu cũ.
- Thêm filter **"Needs Review"** gom các trường hợp thiếu dữ liệu:
  - `make_buy` trống;
  - Buy nhưng không có Vendor;
  - Vendor là "Unknown Vendor".
- Trường hợp "Make nhưng có Vendor" không còn tồn tại sau migrate, vì đã bị chặn bằng ràng buộc (mục 5.1). 69 dòng hiện có được xử lý trước khi migrate (câu hỏi K).

## 5.1 Chuyển đổi Buy ↔ Make

**Nguyên tắc:** Make là sản xuất tại công ty, nên **không có thông tin nhà cung cấp**.

| Chuyển | Product | `supplierinfo` (nhà cung cấp) | UI |
|---|---|---|---|
| Buy → Make | **Giữ** (Part Make vẫn cần product cho BOM ở đợt 3; product không mua/bán nên vô hại) | **Xóa toàn bộ** | Cảnh báo trước khi lưu: "Chuyển sang Make sẽ xóa N nhà cung cấp của Part này"; ẩn nhóm field Purchase |
| Make → Buy | Như cũ (sinh khi nhập Vendor) | Trống, người dùng nhập | Hiện nhóm field Purchase |

- **Truy vết:** khi xóa nhà cung cấp, ghi danh sách đã xóa (Vendor, mã đặt hàng, giá, lead time) vào chatter của Part, để tra lại được nếu chuyển nhầm.
- **Ràng buộc** (`@api.constrains`): Part `make_buy = 'make'` không được có `supplierinfo`. Nhập Vendor cho Part Make sẽ báo lỗi.
- **Khi mở Purchase sau này:** thêm `purchase_ok` theo `make_buy` (mục 7.2); quy tắc xóa nhà cung cấp giữ nguyên.

Part Make có Vendor vẫn hiện trong filter "Needs Review" để người dùng xác nhận.

## 6. Khi nào Part có product

Product **chỉ sinh khi thật sự cần**, không phụ thuộc Buy/Make:
- **Part có dữ liệu Vendor** (Vendor, mã đặt hàng, giá, lead time), vì `supplierinfo` bắt buộc gắn với một product.
  - Áp dụng **cả khi Part đang Pending**. Product không mua/bán nên tạo sớm cũng vô hại.
  - Nếu Part bị **Reject**: gọi `_unlink_or_archive()` cho product. Product chưa thể có giao dịch, nên luôn bị xóa hẳn và không để lại rác.
  - (Bản trước chờ tới lúc Approve mới tạo product. Cách đó sinh ra trạng thái trung gian khó đúng: dữ liệu Vendor nằm tạm trên Part mà chưa có `supplierinfo`, có nguy cơ bị recompute xóa mất. Đã bỏ, xem review #13.)
- Người dùng bấm **"Create / Link Product"**.
- Part được dùng trong BOM (đợt 3).
- **Không** tự tạo product cho Part `obsolete`, Part mã không chuẩn, hoặc Part chưa có `part_number`.
- "Create / Link Product":
  - Tìm product chưa gắn Part nào có `default_code` trùng; nếu có thì liên kết.
  - Không có thì tạo mới.
  - Chạy được cho nhiều Part cùng lúc (bulk).

## 7. Thiết kế kỹ thuật

### 7.1 Liên kết

```python
# part_number_manager.part_number
product_id = fields.Many2one('product.product', copy=False, index=True, ondelete='restrict')
_product_unique = models.UniqueIndex('(product_id) WHERE product_id IS NOT NULL')

# product.product (_inherit)
pnm_part_ids = fields.One2many('part_number_manager.part_number', 'product_id')   # tối đa 1
_default_code_unique = models.UniqueIndex('(default_code) WHERE default_code IS NOT NULL')
```

- `ondelete='restrict'`: không xóa được product đang gắn với Part (từ phía Inventory/Purchase).
- **Xóa Part** (`unlink`): xóa Part trước, sau đó gọi `product._unlink_or_archive()` (cơ chế có sẵn của Odoo):
  - product chưa có giao dịch (PO, phiếu kho, BOM…) → **xóa luôn**, không để lại product rác;
  - product đã có giao dịch → DB chặn xóa, Odoo tự **archive**, giữ nguyên lịch sử chứng từ.
- Luồng thường ngày không xóa Part: Reject chỉ archive Part (product archive theo). Xóa thật chỉ là thao tác của admin.

### 7.2 Đồng bộ Part → Product (một chiều)

Một hàm duy nhất `_sync_product()`, gọi trong `create` / `write` khi các field liên quan đổi. Hàm gom theo lô để import lớn không bị chậm.

| Part | Product |
|---|---|
| `part_number` | `default_code` |
| `short_description` (trống thì dùng `part_number`) | `name` |
| `long_description` | `description_purchase` |
| `active` | `action_archive()` / `action_unarchive()` (archive cả template) |
| — | Luôn đặt `sale_ok = False`, `purchase_ok = False`, `is_storable = False` (phạm vi chỉ quản lý thông tin) |
| — | Lúc tạo: `type = 'consu'`, UoM Units, category mặc định |

Khi mở Purchase sau này, chỉ cần đổi dòng trên thành `purchase_ok = (make_buy != 'make' and state != 'obsolete')` rồi chạy lại đồng bộ.

Phía Product: `write` chặn sửa `default_code` nếu product đang gắn với một Part ("Internal Reference is managed by Part Number").

### 7.3 Field Vendor trên Part chuyển thành compute

Các field `vendor_id`, `vendor_ref`, `reference_price`, `currency_id`, `lead_time` trở thành **compute lưu trữ (stored) có inverse**, lấy từ **vendor chính** (dòng `supplierinfo` đầu tiên theo `sequence`):

- **Đọc:** giữ nguyên tên field. List, search, group by, trang Create New, `find_duplicate_vendor_refs` và bộ chọn "Display In" (`price_display`) đều chạy như cũ.
- **Ghi:** inverse đảm bảo Part có product (tạo nếu chưa có), rồi tạo hoặc cập nhật dòng `supplierinfo` chính.
- Thêm `vendor_code = related('vendor_id.ref')`, hiện trên list và form.
- Tab **"Vendors"** trên form Part hiển thị đầy đủ `seller_ids` của product, dùng khi có nhiều Vendor.
- `currency_id` khi chưa có Vendor: mặc định tiền tệ công ty (giữ hành vi hiện tại).

**Chi tiết bắt buộc (từ review):**

1. **Một compute và một inverse chung cho cả 5 field** (`_compute_main_seller` / `_inverse_main_seller`), không viết riêng cho từng field. Nếu viết riêng, một lần lưu có đủ 5 giá trị sẽ chạy 5 lượt ghi `supplierinfo`, và có thể tạo trùng dòng.
2. **Vendor chính** = dòng đầu tiên của `product_id.product_tmpl_id.seller_ids` theo `(sequence, id)`. Không lọc theo ngày hiệu lực hay công ty, để giá trị hiển thị luôn ổn định.
3. **Ghi giá hoặc mã đặt hàng mà chưa có Vendor:** `supplierinfo` bắt buộc có Vendor, nên inverse dùng "Unknown Vendor". Trang Create New vẫn cho nhập Vendor ref không có Vendor như hiện nay.
4. **Lead time:**
   - Ghi: tuần × 7 → `delay`.
   - Đọc: `ceil(delay / 7)`. Nếu ai đó nhập `delay` lẻ ngày từ phía Purchase (ví dụ 10 ngày), Part hiện 2 tuần, làm tròn lên cho an toàn.
5. **Tìm theo mã đặt hàng của mọi Vendor** (không chỉ vendor chính):
   - `find_duplicate_vendor_refs` truy vấn thẳng `supplierinfo.product_code`.
   - Ô search Vendor ref dùng một field **không lưu** `all_vendor_refs` có hàm search riêng, vì field stored không gắn được hàm search tùy biến.
7. **`load()` import:** Odoo import theo kiểu all-or-nothing, nên một dòng Make có Vendor sẽ làm hỏng cả file. Bổ sung kiểm tra trước trong `load()`: dòng nào vi phạm thì loại ra và báo lỗi riêng, giống cơ chế `conflict_messages` đang có.
8. **Buy → Make** xử lý trong `write`: xóa `supplierinfo` (sudo), ghi chatter. Áp dụng cho mọi đường ghi (form, trang Create New, import).
6. **Depends** khai báo đầy đủ đường dẫn: `product_id.product_tmpl_id.seller_ids.{partner_id, product_code, price, currency_id, delay, sequence}`. Nhờ vậy, khi sửa `supplierinfo` từ phía Purchase, các field trên Part tự recompute. Truy ngược từ `supplierinfo` về Part dùng index trên `product_id`.

### 7.4 Quyền

PNM user **không** cần quyền product. Việc tạo và đồng bộ product/`supplierinfo` là hệ quả có kiểm soát của thao tác trên Part, nên chạy `sudo()` gói gọn trong `_sync_product()` và `_ensure_product()`. Người dùng không sửa được product tùy ý.

## 8. Thay đổi code

### Đợt 1 — Liên kết + đồng bộ + menu

| File | Thay đổi |
|---|---|
| `__manifest__.py` | `depends` thêm `'product'`; version → `19.0.2.0.0` |
| `models/part_number.py` | Thêm `product_id`; `_prepare_product_vals()`, `_ensure_product()`, `_sync_product()`; hook trong `create` / `write`; `action_create_link_product()` |
| `models/product_product.py` (mới) | `pnm_part_ids`; unique `default_code`; chặn sửa `default_code`; smart button mở Part |
| `views/part_number_views.xml` | Smart button "Product"; nút "Create / Link Product" trên form và action trong list; menu Design / Purchased Parts; filter Needs Review |
| `views/product_views.xml` (mới) | Field / smart button "Part Number" trên form product |
| `tests/test_part_product_link.py` (mới) | Xem chi tiết bên dưới |

**`tests/test_part_product_link.py`** kiểm tra:
- tạo Part không có dữ liệu Vendor thì không sinh product;
- Create / Link khớp đúng `default_code`;
- product do PNM tạo luôn có `sale_ok = purchase_ok = False` và `is_storable = False`;
- sửa Part thì product đồng bộ theo;
- archive / unarchive đồng bộ cả template;
- xóa Part: product chưa có giao dịch thì bị xóa, đã có giao dịch thì archive;
- sửa `default_code` từ phía Product bị chặn;
- unique `default_code` hoạt động.

### Đợt 2 — Vendor → supplierinfo

| File | Thay đổi |
|---|---|
| `__manifest__.py` | Version → `19.0.3.0.0`. **Không** thêm `purchase` (`supplierinfo` thuộc module `product`) |
| `models/part_number.py` | Đổi 5 field Vendor thành stored compute + inverse; thêm `vendor_code`, `seller_ids` |
| `data/partner_data.xml` (mới) | Partner "Unknown Vendor" (`noupdate`) |
| `views/part_number_views.xml` | Tab Vendors; cột Vendor code |
| `tests/` | Kiểm tra inverse tạo `supplierinfo`, compute đọc vendor chính, Create New page vẫn lưu được Vendor |

**Không phải sửa:**
- `part_management_page.js` / `.xml`, `pnm_part_number_list.js`, `currency_rate_update.py`: vẫn dùng tên field cũ.
- `load()` import: đi qua `create` / `write` nên inverse tự chạy.

### `hose_fitting_manager`

- **Không phải sửa code ở đợt 1 và 2.** Part assembly tạo từ Builder không có dữ liệu Vendor nên không tự sinh product.
- Đợt 3 dựng `mrp.bom` từ `bom_line` và gọi `_ensure_product()` cho từng component.

## 9. Migrate dữ liệu

### Đợt 1 (`migrations/19.0.2.0.0/post-migrate.py`)

- Schema chỉ thêm cột `product_id` cho phép trống. Không có NOT NULL, không đổi field cũ, nên **rủi ro schema rất thấp**.
- **Không tạo product hàng loạt** ở đợt này. Product sinh dần khi dùng, hoặc qua bulk action "Create / Link Product".
- Rollback: chỉ cần xóa liên kết.

### Đợt 2 (`migrations/19.0.3.0.0/`)

**`pre-migrate.py`** (SQL, trước khi field đổi sang compute):
- Sao lưu `id, vendor_id, vendor_ref, reference_price, currency_id, lead_time` vào bảng `pnm_mig_vendor_backup`.
- **Bắt buộc:** chặn Odoo recompute làm mất dữ liệu cũ trước khi `supplierinfo` được tạo.

**`post-migrate.py`** (ORM, theo lô 1.000, context tắt tracking/chatter):
0. **Kiểm tra điều kiện trước:** nếu vẫn còn Part `make_buy = 'make'` có dữ liệu Vendor (69 dòng bạn sẽ sửa tay), thì **dừng migrate**, báo danh sách mã và rollback. Bước này đảm bảo việc sửa tay đã xong trước khi chạy.
1. Chọn các Part có ít nhất một trong các giá trị `vendor_id`, `vendor_ref`, `reference_price` hoặc `lead_time` (khoảng 2,7k dòng).
2. Mỗi Part: gọi `_ensure_product()`, rồi tạo một dòng `supplierinfo` từ bảng backup:
   - Vendor: lấy `vendor_id`; nếu trống thì dùng "Unknown Vendor";
   - `product_code` = `vendor_ref`;
   - `price` = `reference_price`;
   - `currency_id` = `currency_id`;
   - `delay` = `lead_time × 7`.
3. Recompute các field Vendor trên Part.
4. **Kiểm tra bắt buộc**, sai bất kỳ điều nào thì raise và rollback toàn bộ:
   - mỗi Part trong tập trên có đúng một `supplierinfo`;
   - các field compute khớp 100% với bảng backup (Vendor, ref, price, currency, lead time);
   - `default_code` của product = `part_number`.
5. Giữ `pnm_mig_vendor_backup` vài tuần rồi mới drop.

Mỗi đợt upgrade chạy trong **một transaction**: lỗi ở đâu cũng rollback toàn bộ.

## 10. Kiểm thử và triển khai (mỗi đợt)

1. Chạy unit test trên DB mới (lệnh test docker chuẩn).
2. Clone `jacon_plm_0814` → `jacon_plm_0814_migtest`, chạy upgrade và đo thời gian. Kiểm tra tay:
   - danh sách Part (All / Design / Purchased / Needs Review);
   - trang Create New / Convert Legacy;
   - Import;
   - Approve / Reject;
   - Save trên Hose Builder;
   - menu Products;
   - product do PNM tạo **không** xuất hiện trong ô chọn sản phẩm khi tạo PO/SO.
3. Triển khai lên production và rollback: theo **mục 14**. **Phải hỏi xác nhận trước khi chạy trên DB thật.**
4. Xóa DB clone.

## 11. Đánh giá hiệu năng

### Đọc (mở list / form Part) — gần như không đổi

| Thao tác | Hiện tại | Sau khi đổi | Lý do |
|---|---|---|---|
| Mở list Part (80 dòng/trang) | 1 query đọc cột | **Như cũ** | 5 field Vendor là stored, đọc thẳng từ cột trên bảng Part, không join `supplierinfo` |
| Search / filter / group by Vendor | Theo cột | **Như cũ** | Vẫn là cột stored |
| `price_display` ("Display In") | Compute, không stored | **Như cũ** | Phụ thuộc `reference_price` / `currency_id`, vẫn là cột stored |
| Cột Vendor code (`vendor_id.ref`) | — | Thêm 1 query gộp cho cả trang | Prefetch một lần cho mọi Vendor trên trang, không chạy theo từng dòng |
| Search Vendor ref (mọi Vendor) | `ilike` trên Part | Thêm subquery vào `supplierinfo` | Bảng nhỏ (khoảng 2,7k dòng), có index `product_tmpl_id` |
| Form Part, tab Vendors | — | Thêm 1 query | Chỉ chạy khi mở tab |

**Kết luận:** tốc độ load list và form gần như không đổi, vì dữ liệu hiển thị vẫn là cột stored trên Part.

### Ghi (tạo / sửa Part) — chậm hơn có kiểm soát

| Thao tác | Query thêm (ước tính) | Ghi chú |
|---|---|---|
| Tạo Part không có dữ liệu Vendor | ~0 | Không sinh product |
| Tạo Part có dữ liệu Vendor (đã approved) | +10–20 | Tạo product.template + variant + `supplierinfo` |
| Sửa `short_description` / `state` của Part đã có product | +1–3 | `_sync_product` ghi product |
| Sửa Vendor / Price trên Part | +2–4 | Inverse ghi `supplierinfo`, rồi recompute |
| Import lớn (vài nghìn dòng) | Tăng tuyến tính | **Bắt buộc** gom lô trong `_sync_product` / `_ensure_product`: một `create` cho nhiều product, không tạo từng cái |

Trang Create New thường lưu vài chục dòng mỗi lần, nên chậm hơn khoảng vài trăm ms, chấp nhận được.

### Đo thực tế

Trên DB clone, đo:
- thời gian `web_search_read` của list Part (trước / sau);
- thời gian lưu 50 dòng trên trang Create New;
- thời gian import 1.000 dòng;
- thời gian chạy migrate đợt 2.

## 12. Kết quả review plan (đã sửa trong tài liệu)

| # | Vấn đề | Xử lý |
|---|---|---|
| 1 | Viết riêng inverse cho từng field Vendor → một lần lưu ghi 5 lần, có thể tạo trùng `supplierinfo` | Dùng một compute và một inverse chung (mục 7.3) |
| 2 | Part Pending bị Reject vẫn để lại product | Chỉ sinh product khi `approved` (mục 6) |
| 3 | `find_duplicate_vendor_refs` chỉ thấy mã của vendor chính | Tìm trong `supplierinfo` của mọi Vendor (mục 7.3) |
| 4 | Lead time tuần ↔ ngày lệch khi `delay` không chia hết cho 7 | Đọc bằng `ceil`, ghi bằng ×7 (mục 7.3) |
| 5 | Ghi giá hoặc ref khi chưa có Vendor thì không tạo được `supplierinfo` | Dùng "Unknown Vendor" (mục 7.3) |
| 6 | Part Buy cũ chưa có Vendor (4.206) sẽ không có product | Đã chốt không tạo bù (câu H); sau khi thu hẹp phạm vi, product chỉ cần khi có dữ liệu Vendor nên đây không còn là khoảng trống |
| 7 | Product archive từ phía Inventory không đồng bộ ngược về Part | Chấp nhận (đồng bộ một chiều); ghi rõ trong tài liệu hướng dẫn |
| 8 | `sudo()` khiến chatter của product ghi tác giả là hệ thống, không phải người thao tác | Chấp nhận; lịch sử thao tác vẫn ghi đầy đủ trên chatter của Part |
| 9 | Pre-migrate đợt 2: khi đổi field thường thành stored compute, nếu Odoo recompute thì dữ liệu cũ bị xóa trắng | Đã có bảng backup + kiểm tra khớp 100% (mục 9) |
| 10 | `jacon_plm` cũng cài module | Đã có trong kế hoạch triển khai (mục 10) |
| 13 | Chờ Approve mới tạo product → trạng thái trung gian (Vendor nằm tạm trên Part, chưa có `supplierinfo`) dễ bị recompute xóa mất | Tạo product ngay cả khi Pending; Reject thì xóa product (mục 6) |
| 14 | Field stored không gắn được hàm search tùy biến → search Vendor ref của mọi Vendor không làm được trên chính field `vendor_ref` | Thêm field không lưu `all_vendor_refs` có hàm search riêng (mục 7.3) |
| 15 | `load()` all-or-nothing: một dòng Make có Vendor làm hỏng cả file import | Lọc trước và báo lỗi riêng từng dòng (mục 7.3) |
| 16 | Server thật tự `git pull` nhánh `main` rồi chỉ restart, **không** upgrade module | Merge chỉ trong giờ bảo trì, tạm tắt tác vụ tự cập nhật (mục 14) |
| 17 | `docs/` đang bị `.gitignore` → tài liệu này không được version | Cần quyết: đưa vào git hay giữ local (câu hỏi L) |
| 12 | Bản trước giữ nhà cung cấp khi chuyển Buy → Make: sai, vì Make là sản xuất tại công ty | Xóa `supplierinfo` khi chuyển sang Make (có cảnh báo, ghi chatter) và thêm ràng buộc Make không có Vendor (mục 5.1) |
| 11 | Phạm vi hiện tại chỉ quản lý thông tin, chưa cần quy trình đặt hàng / kho | Tắt mua/bán/kho cho mọi product do PNM tạo; không thêm `purchase` vào `depends`; product chỉ sinh khi có dữ liệu Vendor hoặc khi bấm tay (mục 1, 6, 7.2) |

## 13. Câu hỏi (đã chốt)

> A–F và J được chốt **theo đề xuất** khi bắt đầu code (2026-10-01). Muốn đổi điểm nào thì báo, phần code tương ứng đều nhỏ.

- [x] **A.** Product chỉ sinh khi có dữ liệu Vendor hoặc khi bấm "Create / Link Product".
- [x] **B.** 22.783 Part có `make_buy` trống: **để nguyên**, xử lý dần qua filter Needs Review. Không tự suy luận.
- [x] **C.** Dòng có mã đặt hàng hoặc giá nhưng không có Vendor: gán **"Unknown Vendor"**. Diễn tập: 1.088 dòng (1.080 + 8).
- [x] **D.** Vendor code nhập trực tiếp trên form Vendor (Contact, ô Reference). Part hiển thị lại (cột/ô "Vendor Code", chỉ đọc). Import hàng loạt nếu cần thì làm qua Import của Contacts.
- [x] **E.** Dùng **`sudo()` có kiểm soát**. PNM user không cần quyền product.
- [x] **F.** Tên product khi `short_description` trống = Part Number.
- [x] **J.** **Gộp** đợt 1 và 2 thành một lần triển khai: một version `19.0.2.0.0`, một bộ script migrate.
- [x] **G.** Tồn kho và quy trình đặt hàng: **chưa cần**. Hiện chỉ quản lý thông tin; product luôn `sale_ok = purchase_ok = is_storable = False`.
- [x] **K.** 69 Part Make có dữ liệu Vendor (26 có Vendor, 41 chỉ có mã đặt hàng, 2 chỉ có giá): **bạn tự sửa tay** trước khi migrate. Migrate có bước kiểm tra, còn sót thì tự dừng (mục 9).
- [x] **L.** Tài liệu này **đưa vào git** (`git add -f`; thư mục `docs/` vẫn giữ trong `.gitignore`).
- [x] **M.** Server thật = `C:\odoo-project`; DB production = `jacon_plm`.
- [x] **N.** `odoo_update_module.bat` **chạy tay**, nên không có rủi ro tự kích hoạt khi merge. Runbook bước 1 đổi thành: **không chạy script này trong lúc triển khai**. (Đề xuất riêng, PR khác: nâng cấp script để tự backup và upgrade những module có thay đổi.)
- [x] **H.** 4.206 Part Buy cũ chưa có Vendor: **không tạo bù** khi migrate. Product chỉ sinh khi có người dùng tới (bulk action "Create / Link Product" hoặc khi sửa Part).
- [x] **I.** Xóa Part: xóa luôn product nếu chưa có giao dịch, đã có giao dịch thì archive (`_unlink_or_archive`).

## 14. Phương án triển khai và rollback

### 14.1 Môi trường (cần xác nhận ở câu M)

| Môi trường | Ở đâu | DB | Dùng để |
|---|---|---|---|
| **DEV** | Máy dev (`C:\WORK\odoo-project`) | DB test tạo mới + `jacon_plm_0814` | Viết code, chạy unit test |
| **STAGING** | Máy dev | `jacon_plm_staging`: **restore từ bản backup production mới nhất** | Diễn tập migrate và rollback trên dữ liệu thật, đo thời gian |
| **PRODUCTION** | Server (`C:\odoo-project`) | `jacon_plm` | Người dùng thật |

Lý do STAGING phải dùng bản backup production mới nhất thay vì `jacon_plm_0814`: `0814` là dữ liệu từ tháng 8, có thể đã khác production (thêm Part, đã sửa 69 Part Make). Migrate phải được thử trên đúng dữ liệu sắp chạy thật.

### 14.2 Quản lý code (git)

1. **Nhánh mới từ `origin/main` mới nhất:** `feature/pnm-product-link`.
   - Nhánh hiện tại `addon/jacon_core` đang chậm hơn `main` 17 commit và không có commit riêng, nên không dùng làm gốc.
2. **Commit theo từng bước logic**, mỗi commit chạy được độc lập:
   1. Liên kết product + đồng bộ.
   2. Field Vendor → `supplierinfo`.
   3. Views/menu.
   4. Script migrate.
   5. Tests.
3. **Pull Request vào `main`**, review đầy đủ. **Chưa merge** cho tới khi diễn tập trên STAGING đạt (14.3).
4. **Tag điểm quay lui** trên `main` ngay trước khi merge: `pre-pnm-product-link`. Đây là commit production đang chạy, dùng để rollback code.
5. Merge xong thì tag bản phát hành: `pnm-product-link-v1`.
6. **Merge chỉ trong giờ bảo trì** (14.4), vì server tự `git pull main` và chỉ restart, không upgrade module (`Scripts/odoo_update_module.bat`).

### 14.3 Diễn tập trên STAGING (bắt buộc, chạy lại tới khi sạch)

1. Restore bản backup production mới nhất vào `jacon_plm_staging` bằng `Scripts/restore_odoo.bat` (DB + filestore).
2. Checkout `feature/pnm-product-link`, chạy:
   ```
   odoo -d jacon_plm_staging -u part_number_manager,hose_fitting_manager --stop-after-init
   ```
   Lưu log và **đo thời gian chạy**.
3. Chạy các câu SQL đối chiếu số liệu (mục 9) và checklist UI (mục 10).
4. **Diễn tập cả rollback:** restore lại `jacon_plm_staging` từ backup, checkout tag `pre-pnm-product-link`, restart. Kiểm tra hệ thống chạy lại bình thường và **đo thời gian rollback**.
5. Chỉ khi cả upgrade lẫn rollback đều đạt mới lên lịch triển khai PRODUCTION.

### 14.4 Runbook triển khai PRODUCTION

| Bước | Việc | Ghi chú |
|---|---|---|
| 0 | Thông báo giờ bảo trì; chọn khung giờ đủ dài = thời gian upgrade + thời gian rollback đo ở staging + dự phòng | Ngoài giờ làm việc |
| 1 | **Không** chạy `odoo_update_module.bat` trong lúc triển khai (script chạy tay, chỉ restart, không upgrade) | Câu N |
| 2 | Dừng truy cập của người dùng (thông báo / tạm dừng) | Không để ai ghi dữ liệu trong lúc upgrade |
| 3 | **Backup:** `Scripts/backup_odoo.bat jacon_plm` (DB + filestore). Ghi lại commit hash đang chạy | Bản backup này là điểm rollback DB |
| 4 | **Kiểm tra bản backup dùng được:** restore thử vào `jacon_plm_verify` rồi mở thử | Không bao giờ triển khai khi chưa chắc backup dùng được |
| 5 | Merge PR, tag; trên server: `git fetch` → `git checkout pnm-product-link-v1` | |
| 6 | Upgrade: `odoo -d jacon_plm -u part_number_manager,hose_fitting_manager --stop-after-init`, lưu log | |
| 7 | `docker compose restart odoo`; chạy smoke test (danh sách bên dưới) | Khoảng 10–15 phút |
| 8 | **Go / No-Go** | Go: bật lại tác vụ tự cập nhật, thông báo hoàn tất. No-Go: sang 14.5 |

**Smoke test:**
- Mở list Part và Purchased Parts.
- Tạo 1 Part Buy có Vendor, kiểm tra product + `supplierinfo` được tạo.
- Chuyển Part đó sang Make, kiểm tra cảnh báo và chatter.
- Save trên Hose Builder.
- Mở trang Create New và Convert Legacy.
- Import thử một file nhỏ.

### 14.5 Rollback

| Tình huống | Trạng thái DB | Cách rollback |
|---|---|---|
| **A. Lệnh upgrade (bước 6) báo lỗi** | Không đổi: migrate chạy trong một transaction nên đã tự rollback. Kiểm tra `ir_module_module.latest_version` vẫn là bản cũ | **Chỉ rollback code:** `git checkout pre-pnm-product-link` → restart. Không cần restore DB |
| **B. Upgrade xong, smoke test lỗi nặng** (vẫn trong giờ bảo trì, chưa ai nhập dữ liệu) | Đã đổi | **Rollback toàn bộ:** dừng Odoo → `restore_odoo.bat` bản backup bước 3 vào `jacon_plm` → `git checkout pre-pnm-product-link` → restart → kiểm tra. Không mất dữ liệu |
| **C. Lỗi phát hiện sau khi người dùng đã làm việc** | Đã có dữ liệu mới | **Ưu tiên sửa tiến (hotfix)** trên nhánh mới, qua staging rồi triển khai. Restore DB lúc này sẽ **mất mọi dữ liệu nhập sau triển khai**, nên chỉ làm khi lỗi gây hỏng dữ liệu và đã thống nhất chấp nhận mất phần đó |

**Lưu ý:**
- Bảng backup `pnm_mig_vendor_backup` (mục 9) giữ vài tuần, cho phép đối chiếu hoặc khôi phục riêng dữ liệu Vendor mà không phải restore cả DB.
- **Đường dẫn backup:** `backup_odoo.bat` ghi vào thư mục OneDrive, còn `restore_odoo.bat` mặc định đọc `C:\odoo_backup`. Giữ nguyên hai script (đã chốt). Khi restore hoặc rollback, **luôn truyền đường dẫn đầy đủ** của thư mục backup vừa tạo ở bước 3, ghi sẵn đường dẫn này vào biên bản triển khai.
- Triển khai `jacon_plm_0814` (DB dev) chỉ để phát triển, không phải bước của production.

## 15. Hướng dẫn triển khai từng bước (lệnh cụ thể)

> Lệnh viết cho **Command Prompt (cmd)** trên Windows.
> - **Server production:** thư mục project `C:\odoo-project`, DB `jacon_plm`. Các script (backup, restore, update) nằm trong `C:\odoo-project\Scripts\`.
> - **Máy dev:** thư mục `C:\WORK\odoo-project`. Các script đặt cứng `PROJECT_DIR=C:\odoo-project` (thư mục project trên server), nên **không chạy được nguyên trạng trên máy dev**. Phần staging (15.2) dùng lệnh tay thay cho script.
> - `<BACKUP_DIR>` = đường dẫn đầy đủ của thư mục backup, ví dụ `...\Odoo\data_backup\jacon_plm_20261015_190012`.

### 15.0 Cách nhanh: dùng script (khuyến nghị)

Hai script trong `Scripts\` gói các bước 3–7 của 15.3 và bước rollback. Chạy được trên cả server lẫn máy dev; script tự lấy thư mục project theo vị trí của nó. **Chạy trong cmd, không chạy trong PowerShell.**

| Script | Làm gì |
|---|---|
| `Scripts\upgrade_modules.bat <db> <modules>` | Hỏi xác nhận → backup DB + filestore vào `C:\odoo_upgrade_backups\<db>_<thời gian>\` → restore thử bản backup và so khớp → upgrade, lưu `upgrade.log` → dò lỗi trong log → restart → in version module và **lệnh rollback dựng sẵn** |
| `Scripts\rollback_db.bat <db> <thư mục backup>` | Hỏi xác nhận → dừng Odoo → drop và restore DB → restore filestore → restart |

Ví dụ:
```cmd
Scripts\upgrade_modules.bat jacon_plm part_number_manager,hose_fitting_manager
Scripts\rollback_db.bat jacon_plm "C:\odoo_upgrade_backups\jacon_plm_20261015_190000"
```

- Script **không đụng tới git**. Chuyển code (pull/checkout) làm trước khi chạy; khi rollback thì tự quay code về bản cũ.
- Đã chạy thử cả hai script trên DB tạm `pnm_migtest` (2026-10-01): upgrade đủ 6 bước, rollback khôi phục đúng.

### 15.1 Chuẩn bị (trước ngày triển khai)

| # | Việc | Ai | Xong |
|---|---|---|---|
| 1 | PR `feature/pnm-product-link` đã review và approve, **chưa merge** | Dev | [ ] |
| 2 | Diễn tập STAGING đạt (15.2), đã ghi **thời gian upgrade** và **thời gian rollback** | Dev | [ ] |
| 3 | 69 Part Make có dữ liệu Vendor đã sửa tay trên production (lệnh kiểm tra bên dưới trả về 0) | Bạn | [ ] |
| 4 | Chốt giờ bảo trì = thời gian upgrade + rollback + 30 phút dự phòng; thông báo người dùng | Bạn | [ ] |
| 5 | Ổ chứa backup (OneDrive) còn đủ dung lượng | Bạn | [ ] |

Kiểm tra mục 3 trên server. Kết quả phải là `0`:
```cmd
cd /d C:\odoo-project
docker compose exec -T db psql -U odoo -d jacon_plm -Atc "select count(*) from part_number_manager_part_number where make_buy='make' and (vendor_id is not null or coalesce(vendor_ref,'')<>'' or coalesce(reference_price,0)<>0 or coalesce(lead_time,0)<>0)"
```
Muốn xem danh sách mã thì thay `count(*)` bằng `part_number`.

### 15.2 Diễn tập trên STAGING (máy dev)

**1. Lấy bản backup production mới nhất.**
- Chạy trên server: `C:\odoo-project\Scripts\backup_odoo.bat jacon_plm`.
- Ghi lại `<BACKUP_DIR>` (OneDrive đã đồng bộ sẵn sang máy dev).

**2. Restore vào `jacon_plm_staging`** (trên máy dev):
```cmd
cd /d C:\WORK\odoo-project
docker compose exec -T db dropdb -U odoo --if-exists --force jacon_plm_staging
docker compose exec -T db createdb -U odoo jacon_plm_staging
docker compose exec -T db pg_restore -U odoo -d jacon_plm_staging --no-owner --role=odoo < "<BACKUP_DIR>\jacon_plm.dump"
docker compose exec -T odoo bash -c "rm -rf /tmp/st && mkdir -p /tmp/st && tar xzf - -C /tmp/st && rm -rf /var/lib/odoo/.local/share/Odoo/filestore/jacon_plm_staging && mv /tmp/st/jacon_plm /var/lib/odoo/.local/share/Odoo/filestore/jacon_plm_staging && rm -rf /tmp/st" < "<BACKUP_DIR>\filestore.tar.gz"
```

**3. Upgrade bằng code mới**, ghi log và đo thời gian:
```cmd
git fetch && git checkout feature/pnm-product-link
docker compose restart odoo
echo %time%
docker compose exec -T odoo odoo -d jacon_plm_staging -u part_number_manager,hose_fitting_manager --stop-after-init > upgrade_staging.log 2>&1
echo %time%
docker compose restart odoo
```
Mở `upgrade_staging.log`: **không được có dòng `ERROR` hay `Traceback`**.

**4. Đối chiếu số liệu** (15.5) và chạy checklist UI (mục 10) trên `jacon_plm_staging`.

**5. Diễn tập rollback B** (15.6) trên `jacon_plm_staging`, đo thời gian.

**6.** Lỗi ở bất kỳ bước nào: sửa code trên nhánh feature và **chạy lại từ bước 2**.

### 15.3 Triển khai PRODUCTION (trên server, trong giờ bảo trì)

**Bước 1. Ghi lại commit đang chạy** (điểm quay lui code):
```cmd
cd /d C:\odoo-project
git rev-parse HEAD
git status
```
`git status` phải sạch, không có file sửa tay trên server.

**Bước 2. Dừng người dùng.**
- Thông báo dừng sử dụng.
- **Không** chạy `odoo_update_module.bat` trong suốt quá trình.

**Bước 3. Backup và ghi lại `<BACKUP_DIR>`:**
```cmd
C:\odoo-project\Scripts\backup_odoo.bat jacon_plm
```

**Bước 4. Kiểm tra bản backup dùng được.** Restore thử vào DB tạm rồi đếm số Part; phải bằng số trên production:
```cmd
docker compose exec -T db createdb -U odoo jacon_plm_verify
docker compose exec -T db pg_restore -U odoo -d jacon_plm_verify --no-owner --role=odoo < "<BACKUP_DIR>\jacon_plm.dump"
docker compose exec -T db psql -U odoo -d jacon_plm_verify -Atc "select count(*) from part_number_manager_part_number"
docker compose exec -T db psql -U odoo -d jacon_plm -Atc "select count(*) from part_number_manager_part_number"
docker compose exec -T db dropdb -U odoo jacon_plm_verify
```

**Bước 5. Merge PR vào `main` (GitHub), tag, rồi lấy code mới về server:**
```cmd
git fetch --tags
git pull --ff-only
git log --oneline -1
```
- Dùng `git pull` (không checkout tag) để server vẫn ở nhánh `main`, các lần cập nhật sau chạy bình thường.
- Commit in ra phải là commit đã gắn tag `pnm-product-link-v1`.

**Bước 6. Upgrade module:**
```cmd
docker compose restart odoo
docker compose exec -T odoo odoo -d jacon_plm -u part_number_manager,hose_fitting_manager --stop-after-init > upgrade_prod.log 2>&1
```
Mở `upgrade_prod.log` và kiểm tra:
- **Có `ERROR` / `Traceback`:** sang rollback A (15.6).
- **Sạch:** sang bước 7.

**Bước 7. Restart và kiểm tra:**
```cmd
docker compose restart odoo
```
- Đối chiếu số liệu (15.5).
- Smoke test (mục 14.4).

**Bước 8. Go / No-Go.**
- **Go:** thông báo người dùng làm việc lại. Lưu `upgrade_prod.log` cùng thư mục backup.
- **No-Go:** rollback B (15.6).

### 15.4 Kiểm tra phiên bản module

```cmd
docker compose exec -T db psql -U odoo -d jacon_plm -c "select name, state, latest_version from ir_module_module where name in ('part_number_manager','hose_fitting_manager')"
```
- Upgrade thành công: `latest_version` là version mới (`19.0.3.0.0` nếu gộp đợt 1 và 2 theo câu J).
- Upgrade lỗi: vẫn là version cũ.

### 15.5 Đối chiếu số liệu sau upgrade

Mọi kết quả đếm "lỗi" phải bằng **0**:
```cmd
docker compose exec -T db psql -U odoo -d jacon_plm -c "select 'Vendor data but no product' as check_name, count(*) from pnm_mig_vendor_backup b join part_number_manager_part_number p on p.id=b.id where p.product_id is null union all select 'Vendor data but no supplierinfo', count(*) from pnm_mig_vendor_backup b join part_number_manager_part_number p on p.id=b.id join product_product pp on pp.id=p.product_id where not exists (select 1 from product_supplierinfo s where s.product_tmpl_id=pp.product_tmpl_id) union all select 'default_code differs from part_number', count(*) from part_number_manager_part_number p join product_product pp on pp.id=p.product_id where pp.default_code is distinct from p.part_number union all select 'Vendor fields differ from backup', count(*) from pnm_mig_vendor_backup b join part_number_manager_part_number p on p.id=b.id where coalesce(p.vendor_ref,'') <> coalesce(b.vendor_ref,'') or coalesce(p.reference_price,0) <> coalesce(b.reference_price,0) union all select 'PNM product saleable/purchasable', count(*) from part_number_manager_part_number p join product_product pp on pp.id=p.product_id join product_template t on t.id=pp.product_tmpl_id where t.sale_ok or t.purchase_ok"
```
Tên bảng và cột lấy theo thiết kế ở mục 7–9. Câu lệnh sẽ được chạy kiểm tra thật trên STAGING trước khi dùng cho production.

### 15.6 Rollback (lệnh cụ thể)

**Rollback A — lệnh upgrade lỗi (DB tự rollback, chỉ quay code):**
```cmd
cd /d C:\odoo-project
git checkout pre-pnm-product-link
docker compose restart odoo
```
- Kiểm tra version module vẫn là bản cũ (15.4).
- Sau đó trên GitHub, **revert merge commit** vào `main`, rồi trên server chạy `git checkout main && git pull --ff-only`, để `main` và server khớp nhau trước lần cập nhật tiếp theo.

**Rollback B — upgrade xong nhưng phải quay về** (trong giờ bảo trì, chưa ai nhập dữ liệu):
```cmd
cd /d C:\odoo-project
git checkout pre-pnm-product-link
docker compose stop odoo
docker compose exec -T db dropdb -U odoo --force jacon_plm
docker compose exec -T db createdb -U odoo jacon_plm
docker compose exec -T db pg_restore -U odoo -d jacon_plm --no-owner --role=odoo < "<BACKUP_DIR>\jacon_plm.dump"
docker compose start odoo
```
- **Chỉ restore DB, không cần restore filestore:** migrate không tạo hay xóa file đính kèm. File assets mới sinh ra trong filestore không ảnh hưởng DB cũ.
- Không dùng `restore_odoo.bat` ở đây: script này drop DB không có `--force`, nên lỗi nếu Odoo còn kết nối; và nó cần container Odoo đang chạy để restore filestore.
- Sau đó: kiểm tra version module (15.4), đếm số Part khớp với trước triển khai, mở thử vài màn hình. Rồi revert merge commit trên GitHub như rollback A.

**Rollback C — lỗi phát hiện sau khi người dùng đã làm việc:** không restore DB (sẽ mất dữ liệu mới). Sửa tiến bằng hotfix: nhánh mới từ `main`, diễn tập lại 15.2, triển khai lại 15.3.

### 15.7 Sau triển khai

- **Theo dõi 1–2 ngày:** log Odoo (`docker compose logs --since 1h odoo`) và phản hồi người dùng.
- **Sau vài tuần ổn định:**
  - drop bảng backup: `drop table pnm_mig_vendor_backup;`
  - xóa DB staging trên máy dev.
- Cập nhật trạng thái tài liệu này thành **"Đã triển khai"**, kèm ngày, commit và đường dẫn bản backup.

## 16. Kết quả code và diễn tập (2026-10-01)

### Điều chỉnh so với plan khi code

| Điểm | Plan | Thực tế | Lý do |
|---|---|---|---|
| Reject Part | Xóa product | **Archive** product (tự động qua đồng bộ `active`) | Reject = archive để còn hoàn tác được; xóa product sẽ mất luôn dữ liệu Vendor của Part |
| `is_storable` | Đặt `False` | Không gán | Field thuộc module `stock`; module chỉ phụ thuộc `product`. Mặc định đã là `False` |
| Danh sách Vendor | `seller_ids` | `variant_seller_ids` | `seller_ids` lọc theo công ty đang chọn → giá trị trên Part có thể nhảy theo công ty |
| Phiên bản | 2 đợt (`19.0.2.0.0`, `19.0.3.0.0`) | Một version `19.0.2.0.0` | Câu J |
| Field đang ghi | — | Sau inverse, đánh dấu tính lại 5 field Vendor | Odoo bảo vệ field đang ghi khỏi recompute → ô Vendor trên Part không hiện "Unknown Vendor" (phát hiện nhờ test) |

### File đã đổi (`part_number_manager`)

| File | Nội dung |
|---|---|
| `__manifest__.py` | `depends` + `product`; version `19.0.2.0.0`; thêm `data/partner_data.xml`, `views/product_views.xml` |
| `models/part_number.py` | `product_id`; 5 field Vendor thành stored compute + một inverse chung; `vendor_code`, `all_vendor_refs`, `seller_ids`; `_ensure_product`, `_sync_product`, `action_create_link_product`; Buy → Make xóa Vendor (cảnh báo + chatter); ràng buộc Make không có Vendor; `unlink`; `find_duplicate_vendor_refs` tìm mọi Vendor; `load()` lọc dòng Make có Vendor |
| `models/product.py` (mới) | Unique `default_code`; chặn sửa `default_code` khi đã gắn Part; nút mở Part trên form product |
| `data/partner_data.xml` (mới) | "Unknown Vendor" |
| `views/part_number_views.xml` | Nút "Create / Link Product" + smart button Product; nhóm Vendor ẩn khi Make; tab Vendors; cột Vendor Code; filter Needs Review; action Design / Purchased Parts; thao tác hàng loạt |
| `views/part_number_menus.xml` | Menu Design Parts, Purchased Parts |
| `views/product_views.xml` (mới) | Smart button Part Number trên form product |
| `migrations/19.0.2.0.0/pre-migrate.py` (mới) | Chặn nếu còn Part Make có dữ liệu Vendor; backup `pnm_mig_vendor_backup` |
| `migrations/19.0.2.0.0/post-migrate.py` (mới) | Tạo product + `supplierinfo` theo lô 1.000; tính lại field; 5 bước kiểm tra, sai thì rollback |
| `tests/test_part_product_link.py` (mới) | 15 test |

`hose_fitting_manager`: không đổi code. Đã cài cùng trên DB test và upgrade cùng trên bản sao, không lỗi.

### Kết quả

- **Unit test:** 15/15 đạt (DB mới, cài cả `hose_fitting_manager`).
- **Diễn tập trên bản sao `jacon_plm_0814`:**
  - Lần 1: upgrade **tự dừng** vì còn 69 Part Make có dữ liệu Vendor; DB giữ nguyên version `19.0.1.0.0`, không còn bảng backup (đã rollback sạch).
  - Lần 2 (sau khi giả lập sửa tay trên bản sao): upgrade xong trong **11 giây**.
    - Chuyển 2.705 Part có dữ liệu Vendor → 2.705 product + 2.705 dòng `supplierinfo` (1.088 dòng dùng "Unknown Vendor").
    - 5 bước kiểm tra đều = 0.
- **Tốc độ load list Part (80 dòng):** khoảng 12 ms cả trước lẫn sau. Search mã đặt hàng trên mọi Vendor: 4 ms.

### Chưa làm

- **Chưa kiểm tra giao diện trên trình duyệt.** Container Odoo đang chạy dùng code cũ; restart để nạp code mới sẽ làm hai DB dev chưa upgrade (`jacon_plm_0814`, `jacon_plm`) báo lỗi (xem mục 17).
- Chưa diễn tập với **bản backup production mới nhất** (mục 15.2), chưa diễn tập rollback.
- Chưa commit, chưa tạo PR.

## 17. Lưu ý cho máy dev khi đang ở nhánh này

- Code mới cần cột `product_id`. **Restart Odoo khi DB chưa upgrade sẽ lỗi** ở các màn hình Part.
- `jacon_plm_0814` hiện chưa upgrade được vì còn 69 Part Make có dữ liệu Vendor (bước chặn hoạt động đúng). Muốn dùng code mới trên DB dev thì phải sửa 69 Part đó (hoặc đổi sang Buy) trước, rồi upgrade.
- Quay lại làm việc khác: `git switch` sang nhánh cũ rồi restart Odoo, DB dev vẫn chạy bình thường vì chưa bị migrate.

## 18. Vendor hiển thị "Code - Name" và Create Vendor (2026-10-01)

**Quyết định:**
- Vendor Code là duy nhất (kiểm tra khi tạo qua hộp thoại).
- Bỏ ô Vendor Code riêng.
- Vendor không khớp thì bắt buộc tạo qua hộp thoại.
- Định dạng hiển thị: `Code - Name`.

| Phần | Thay đổi |
|---|---|
| Hiển thị | `res.partner` hiện `<code> - <name>` chỉ khi có context `pnm_vendor_display` (các ô Vendor trong module Part Number). Contacts, PO, hóa đơn không đổi. Chỉ có 1 trong 2 thì hiện 1. Vendor chỉ có mã thì lưu tên = mã (Odoo bắt buộc tên) và chỉ hiện mã |
| List / form Part | Một ô Vendor dạng `Code - Name`; bỏ cột/ô Vendor Code; search Vendor theo tên hoặc mã |
| Trang Create / Convert | Gợi ý theo tên hoặc mã; dòng cuối dropdown **+ Create Vendor "…"** mở hộp thoại (Name / Code, cần ít nhất 1). Dán hoặc gõ chính xác mã / tên / `Code - Name` thì tự nhận đúng Vendor; không khớp thì báo lỗi và chặn Save (không còn tự tạo Vendor theo tên khi Save) |
| Hộp thoại | Mã đã tồn tại → chặn, có nút **Use this Vendor**; tên trùng → hỏi lại (**Use this Vendor** / **Create anyway**) |
| `PnmCombobox` | Thêm prop tùy chọn `createLabel` / `onCreate`; nơi khác (Hose Builder…) không truyền nên không đổi |

**Kiểm tra:**
- 20/20 unit test (thêm 5 test cho Vendor).
- Trên `pnm_migtest`: view dựng được; ô Vendor đọc ra `V001 - Unknown Vendor`; search theo mã được; bundle JS biên dịch có hộp thoại mới.
- **Chưa** thao tác thử trên trình duyệt.

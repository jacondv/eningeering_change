# Hướng dẫn cài đặt Odoo 19.0 + OdoPLM (OmniaSolutions) trên Docker

Tài liệu này hướng dẫn cài đặt Odoo Community 19.0 kèm module PLM mã nguồn mở
**OdoPLM** (https://github.com/OmniaGit/odooplm), chạy bằng Docker/Docker Compose,
làm nền tảng để phát triển thêm module quản lý thay đổi (Change Management:
RPN, DCR number, BOC approval...).

---

## 1. Yêu cầu trước khi bắt đầu

- Đã cài **Docker Desktop** (Windows: cần bật WSL2 backend) hoặc Docker Engine (Linux)
- Đã cài **Git**
- Kiểm tra Docker hoạt động:
  ```bash
  docker --version
  docker compose version
  ```

---

## 2. Cấu trúc thư mục dự án

Tạo thư mục làm việc và các thư mục con cần thiết:

```bash
mkdir -p odoo-project/config odoo-project/addons
cd odoo-project
```

Cấu trúc cuối cùng sẽ như sau:

```
odoo-project/
├── docker-compose.yml
├── Dockerfile
├── config/
│   └── odoo.conf
└── addons/
    ├── odooplm/                  <- clone từ GitHub OmniaGit/odooplm
    └── my_change_management/     <- module custom sẽ code sau (RPN, DCR...)
```

---

## 3. Tải mã nguồn OdoPLM

Clone đúng nhánh `19.0` (nhánh đang được OmniaSolutions phát triển tích cực):

```bash
cd addons
git clone --branch 19.0 https://github.com/OmniaGit/odooplm.git
cd ..
```

---

## 4. Tạo file `Dockerfile`

OdoPLM cần thêm một số thư viện Python (cadquery, ezdxf, matplotlib, numpy-stl,
to-3mf...) nên không dùng trực tiếp image `odoo:19.0` gốc mà build thêm một lớp:

```dockerfile
FROM odoo:19.0

USER root

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    python3-dev \
    libgl1 \
    libglx-mesa0 \
    && rm -rf /var/lib/apt/lists/*

COPY addons/odooplm/aaa_requirements.txt /tmp/odooplm_requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/odooplm_requirements.txt
USER odoo
```

> Nếu chỉ dùng các module cơ bản (`plm`, `plm_engineering`, `plm_compare_bom`)
> mà KHÔNG cài `plm_web_3d` (xem 3D trên trình duyệt), có thể một số thư viện
> nặng trong `aaa_requirements.txt` không cần thiết — nếu build lỗi do thư viện
> nào đó, có thể tạm bỏ dòng tương ứng để cài sau.

---

## 5. Tạo file `docker-compose.yml`

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - odoo-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 10s
      timeout: 5s
      retries: 5

  odoo:
    build: .
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8069:8069"
      - "8072:8072"
    environment:
      HOST: db
      USER: odoo
      PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - odoo-web-data:/var/lib/odoo
      - ./addons:/mnt/extra-addons
      - ./config:/etc/odoo

volumes:
  odoo-db-data:
  odoo-web-data:
```

> **Đổi mật khẩu:** thay `odoo_secure_pass` bằng mật khẩu mạnh thật sự trước khi
> dùng ở môi trường thật (không chỉ để test).

---

## 6. Tạo file `config/odoo.conf`

```ini
[options]
addons_path = /mnt/extra-addons,/mnt/extra-addons/odooplm,/usr/lib/python3/dist-packages/odoo/addons
admin_passwd = doi_mat_khau_master_o_day
db_host = db
db_port = 5432
db_user = odoo
db_password = odoo_secure_pass
```

> `admin_passwd` là mật khẩu quản trị cấp cao nhất (dùng khi tạo/xóa database),
> khác với mật khẩu đăng nhập người dùng thông thường — nhớ đổi thành giá trị
> riêng, không dùng giá trị mẫu.

---

## 7. Build và khởi chạy

```bash
docker compose build
docker compose up -d
```

Theo dõi log để chắc chắn không lỗi:

```bash
docker compose logs -f odoo
```

Truy cập: **http://localhost:8069**

Lần đầu truy cập, Odoo sẽ yêu cầu tạo database mới — điền tên database,
email/mật khẩu admin, chọn "Demo data: No" nếu không cần dữ liệu mẫu.

---

## 8. Cài đặt các module cần thiết

Sau khi vào được giao diện Odoo:

1. Vào **Settings → General Settings** → cuộn xuống cuối → bật
   **Developer Tools → Activate the developer mode**
2. Vào **Apps** → nhấn **Update Apps List** (góc trên bên phải, cần bật
   Developer Mode mới thấy nút này)
3. Gỡ bộ lọc "Apps" mặc định (bấm x trên ô lọc) để tìm được module không
   nằm trong danh sách app chính thức của Odoo
4. Tìm và cài lần lượt theo đúng thứ tự:
   - **`plm`** — module nền tảng, bắt buộc cài trước tiên
   - **`plm_engineering`** — tách Engineering BOM riêng khỏi Manufacturing BOM
   - **`plm_compare_bom`** — so sánh bản vẽ/BOM giữa các revision
   - `plm_web_3d` — **tùy chọn**, chỉ cài nếu cần xem file CAD 3D trực tiếp
     trên trình duyệt (nặng hơn, cần đủ thư viện đã cài ở Dockerfile)

---

## 9. Chuẩn bị module custom (Change Management: RPN, DCR, BOC)

Tạo khung sẵn cho module riêng, tách biệt hoàn toàn khỏi code gốc của OdoPLM
để dễ cập nhật OdoPLM sau này mà không bị mất code custom:

```bash
mkdir -p addons/my_change_management/models
mkdir -p addons/my_change_management/views
mkdir -p addons/my_change_management/security
```

Tạo file `addons/my_change_management/__manifest__.py`:

```python
{
    'name': 'Change Management - RPN & BOC',
    'version': '19.0.1.0.0',
    'summary': 'Quản lý Change Log: RPN, DCR number, BOC approval',
    'depends': ['plm', 'plm_engineering', 'mail'],
    'author': 'Your IT Team',
    'data': [
        'security/ir.model.access.csv',
        'views/change_log_views.xml',
    ],
    'installable': True,
    'application': False,
}
```

Sau khi có nội dung `models.py`, `views/*.xml`, `security/ir.model.access.csv`
đầy đủ (phần này sẽ code chi tiết ở bước tiếp theo), cài module bằng cách:
quay lại **Apps → Update Apps List → tìm "Change Management - RPN & BOC" → Install**.

---

## 10. Các lệnh vận hành thường dùng

| Việc cần làm | Lệnh |
|---|---|
| Xem log real-time | `docker compose logs -f odoo` |
| Dừng toàn bộ | `docker compose down` |
| Dừng nhưng giữ dữ liệu | `docker compose stop` |
| Khởi động lại sau khi sửa code module | `docker compose restart odoo` |
| Vào shell bên trong container Odoo | `docker compose exec odoo bash` |
| Backup database | `docker compose exec db pg_dump -U odoo <ten_database> > backup_$(date +%Y%m%d).sql` |
| Rebuild lại image (sau khi sửa Dockerfile) | `docker compose build --no-cache` |

---

## 11. Lưu ý khi phát triển module custom

- Sau khi sửa code Python trong `my_change_management`, cần **Update Apps List**
  và nhấn **Upgrade** module đó trong Apps (không phải chỉ restart container)
  để Odoo nạp lại code mới.
- Nên bật chế độ tự nạp lại XML khi đang sửa giao diện (chạy trong
  `docker compose exec odoo bash` rồi thêm cờ `--dev=xml` nếu cần debug nhanh).
- Luôn tạo **database staging riêng** để test module custom trước khi áp dụng
  vào database chính thức đang dùng thật.

---

## 12. Tài liệu tham khảo

- OdoPLM (OmniaSolutions): https://github.com/OmniaGit/odooplm
- Tài liệu đầy đủ OdoPLM: https://odooplm.omniasolutions.website

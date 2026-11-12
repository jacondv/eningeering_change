# Hướng dẫn cài đặt Office Documents lên production

Áp dụng cho `jacon_office`, `jacon_office_project` và `onlyoffice_odoo`, trên máy chạy docker compose
giống repo này. Chỗ nào khác với production của bạn thì điều chỉnh. Kiến trúc và quyền: xem
`docs/Office_Documents_TechSpec.md` (chỉ có trên máy dev, thư mục `docs/` bị `.gitignore`).

## 0. Cần chốt trước

1. **RAM trống** khoảng 2-4 GB cho ONLYOFFICE (đo ở dev: 0,9 GB khi nghỉ), đĩa trống khoảng 4 GB cho image.
2. **Odoo production mở bằng HTTP hay HTTPS?** (nhìn thanh địa chỉ). Hiện đang dùng **HTTP**: không cần
   tên miền, chứng chỉ hay proxy, bỏ qua bước 4. Nếu sau này chuyển sang HTTPS thì ONLYOFFICE cũng phải
   có địa chỉ HTTPS cho trình duyệt (bước 4), nếu không trình duyệt chặn.
3. **Tên database production** (để đặt `dbfilter`).
4. Production đã có `jacon_core` và `jacon_documents` (addon này phụ thuộc vào chúng).

## 1. Đưa code lên `main`

Merge nhánh `addon/jacon_office` vào `main` (PR), rồi trên máy production: `git pull`.

## 2. Sao lưu (bắt buộc)

- Database: `docker compose exec -T db pg_dump -U odoo -Fc <tên_db> > backup_truoc_office.dump`
- **Filestore** (volume `odoo-web-data`): file tài liệu nằm ở đó. Chép thư mục filestore sang nơi khác.
- Giữ bản sao `config/odoo.conf` và `.env` hiện tại.

## 3. Chuẩn bị và chạy

Làm trước, không ảnh hưởng ai (Odoo vẫn chạy bình thường):

```
docker compose pull onlyoffice office_gateway   # ONLYOFFICE khoảng 3 GB, nginx nhỏ
docker compose build odoo           # thêm thư viện python3-jwt, 1-2 phút
```

Sửa cấu hình:

1. `.env`: thêm một dòng, khoá 32 ký tự trở lên (không dùng lại khoá ngắn của dev):
   `ONLYOFFICE_JWT_SECRET=<kết quả của: openssl rand -hex 32>`
2. `config/odoo.conf` (file cục bộ, không nằm trong git): đặt **`dbfilter = ^<tên_db>$`**.
   Tên khoá là `dbfilter`, **không phải** `db_filter` (khoá này bị Odoo bỏ qua). ONLYOFFICE gọi Odoo
   không đăng nhập; nếu Odoo thấy nhiều DB thì trả 404 và connector báo
   "Error while downloading the document file to be converted". Hệ quả: các DB khác không vào được
   qua web (dữ liệu vẫn nguyên).
3. **Mở cổng 8082** trên tường lửa của máy production (Windows Defender Firewall: Inbound Rule, TCP 8082),
   để máy người dùng truy cập được `http://<địa-chỉ-máy>:8082/`. Giữ nguyên `"8082:80"` trong
   `docker-compose.yml`. Cổng 8082 do container `office_gateway` (nginx) công bố; ONLYOFFICE thì nằm trong
   mạng nội bộ `office_net`, **không ra được internet** (Odoo và DB vẫn ra được như cũ). Cấu hình của
   cổng vào nằm ở `config/onlyoffice-nginx.conf`. (Chỉ khi dùng reverse proxy ở bước 4 mới đổi thành
   `"127.0.0.1:8082:80"`.)

Khởi động (khoảng 10-30 giây Odoo không dùng được vì container `odoo` được tạo lại; nên làm lúc ít
người dùng):

```
docker compose up -d
curl http://localhost:8082/healthcheck      # phải trả: true (lần đầu ONLYOFFICE mất 1-2 phút)
```

## 4. Chỉ khi Odoo chạy HTTPS: địa chỉ HTTPS cho ONLYOFFICE (bỏ qua nếu dùng HTTP)

Cần một tên miền con, ví dụ `office.<công-ty>`, chứng chỉ, và proxy `https://office.<công-ty>` tới `127.0.0.1:8082`, **bắt buộc có WebSocket**. Mẫu nginx (chưa
kiểm thử trên hạ tầng của bạn):

```
server {
  server_name office.<công-ty>;
  # listen 443 ssl; ... chứng chỉ của bạn
  location / {
    proxy_pass http://127.0.0.1:8082;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 100m;
  }
}
```

## 5. Cài vào Odoo

1. Apps, Update Apps List.
2. Cài `onlyoffice_odoo` trước, rồi **Office Documents** (`jacon_office`); `jacon_office_project` tự cài theo.
   Hoặc dòng lệnh, rồi khởi động lại:
   ```
   docker compose exec -T -u odoo odoo odoo -d <db> -i onlyoffice_odoo,jacon_office,jacon_office_project --stop-after-init --http-port=8899 --gevent-port=8902
   docker compose restart odoo
   ```
3. **Settings, ONLYOFFICE**, điền:
   - Document Server Public URL (địa chỉ **trình duyệt người dùng** dùng): với HTTP là
     `http://<địa-chỉ-giống-lúc-mở-Odoo>:8082/`, ví dụ Odoo mở bằng `http://192.168.1.10:8069` thì điền
     `http://192.168.1.10:8082/`. **Không dùng `localhost`**: trên máy người dùng nó trỏ về chính máy họ.
     Nếu có proxy HTTPS (bước 4) thì điền `https://office.<công-ty>/`.
   - Document Server Inner URL (Server address for internal requests from ONLYOFFICE Docs): `http://onlyoffice/`
   - Odoo URL (ONLYOFFICE Docs address for internal requests from the server): `http://odoo:8069/` (tên service Odoo trong mạng docker; sửa nếu production đặt tên khác).
   - Document Server JWT Secret: đúng giá trị `ONLYOFFICE_JWT_SECRET` trong `.env`.

   Bấm **Save**. Save chỉ kiểm tra kết nối khi có giá trị thay đổi; thành công thì im lặng, lỗi thì hiện
   hộp đỏ ("Authorization error" nghĩa là secret sai).
4. **Settings, Office Documents** (cần quyền Manager): số Rev giữ lại (mặc định 3, 0 là không giữ).

## 6. Kiểm tra sau khi cài

1. Mở một Project, tab **Documents**, **+ Document**, Create and Edit: trình soạn mở ở tab mới.
2. Gõ vài chữ, đóng tab. Quay lại tab Documents: Rev tăng thành 2, có Rev cũ (biểu tượng đồng hồ).
3. Biểu tượng mắt mở được PDF.
4. Đăng nhập người dùng thường: chỉ thấy tài liệu của Project mà họ xem được.
5. Lỗi thì xem: `docker compose logs --tail 100 onlyoffice` và `docker compose logs --tail 100 odoo`.

## 7. Quay lại nếu hỏng

- Gỡ module `jacon_office` ở Apps (mất dữ liệu tài liệu, vì vậy phải sao lưu), rồi
  `docker compose stop onlyoffice`. Module khác không bị ảnh hưởng vì không module nào phụ thuộc vào nó.
- Hoặc khôi phục dump DB cùng filestore từ bước 2.

## Lưu ý

- **Font công ty**: ONLYOFFICE thiếu font sẽ thay font khác khi hiển thị và khi tạo PDF; cần chép font
  vào container ONLYOFFICE.
- Bản Community của ONLYOFFICE giới hạn khoảng 20 kết nối cùng lúc; xem PDF không tính.
- Odoo Admin tool có thể không build image hay `up` container mới: phần `build` và `up -d` ở bước 3
  làm tay một lần.
- Sự cố thường gặp: 404 "No database is selected" khi ONLYOFFICE tải file là do Odoo thấy nhiều hơn
  một database (xem `dbfilter` ở bước 3).

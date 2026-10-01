# Cổng in Raspberry Pi cho Odoo 19

Module gửi các báo cáo `qweb-pdf` và `qweb-text` từ Odoo tới một Raspberry Pi/Linux Gateway. Gateway chọn PDF hoặc ZPL theo hồ sơ máy in, rồi giao file cho CUPS để in.

Người dùng có thể bấm In bằng máy tính hoặc PDA: thiết bị chỉ kết nối tới Odoo; **Odoo server** mới là nơi gửi file tới Pi. PDA không cần cài driver, không cần truy cập Pi và không gặp CORS.

## Luồng in

```text
Máy tính / PDA → Odoo → Pi Print Gateway → CUPS → Máy in
```

## 1. Điều kiện trước khi cài

- Thư mục này phải nằm trong `addons_path` của Odoo.
- Odoo server phải gọi được `http://IP_PI:8080`.
- Pi/Linux phải đã kết nối được tới máy in và CUPS phải in thử thành công.
- Cổng 8080 chỉ nên mở cho IP của Odoo server, không mở công khai Internet.

## 2. Cài Gateway trên Raspberry Pi/Linux

Từ máy đang chứa source Odoo, đồng bộ thư mục sang Pi qua SSH. Ví dụ Pi có IP `10.119.54.97`, user `pi`:

```bash
ssh pi@10.119.54.97 'mkdir -p ~/pi_print_gateway'

rsync -avz --progress \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  /opt/odoo19_dev/odoo/Custom_addons/pi_print_gateway/ \
  pi@10.119.54.97:~/pi_print_gateway/
```

Trên Pi, chạy installer:

```bash
ssh -t pi@10.119.54.97 \
  'cd ~/pi_print_gateway && chmod +x install.sh && sudo ./install.sh'
```

Installer cài Python, CUPS client, service `pi-print-gateway`, tạo cấu hình `/etc/pi-print-gateway/config.yml` và sinh một API key. Lưu API key để nhập vào Odoo.

Kiểm tra service:

```bash
sudo systemctl status pi-print-gateway --no-pager
sudo journalctl -u pi-print-gateway -f
```

## 3. Kiểm tra queue CUPS trên Pi

```bash
lpstat -p -d
```

Ví dụ kết quả:

```text
printer BROTHER_MFC is idle
system default destination: BROTHER_MFC
```

Tên `BROTHER_MFC` là queue cần khai báo trong Gateway. Có thể in thử PDF trực tiếp trước khi cấu hình Gateway:

```bash
lp -d BROTHER_MFC /duong-dan/thu.pdf
```

Nếu CUPS chưa có máy in, hãy tạo queue trên web CUPS hoặc cấu hình theo [SERVER_SETUP.md](SERVER_SETUP.md).

## 4. Cấu hình Gateway cho máy in PDF

Mở file trên Pi:

```bash
sudo nano /etc/pi-print-gateway/config.yml
```

Ví dụ cho Brother MFC nhận PDF. Giữ lại API key do installer tạo:

```yaml
server:
  host: 0.0.0.0
  port: 8080
  api_key: GIU_NGUYEN_API_KEY_CUA_BAN
  max_file_size_mb: 50
  storage_dir: /var/lib/pi-print-gateway/jobs
  delete_after_submit: false

default_printer: brother_pdf

printers:
  brother_pdf:
    type: cups
    printer_name: BROTHER_MFC
    format: pdf
    raw: false
    extensions: [pdf]
    options:
      media: A4
      fit-to-page: "true"
```

`printer_name` phải trùng hoàn toàn với tên trả về bởi `lpstat -p -d`. Không để trùng hai block `default_printer` hoặc `printers` trong YAML.

Sau khi lưu:

```bash
sudo systemctl restart pi-print-gateway
```

Kiểm tra profile và trạng thái CUPS:

```bash
PI_GATEWAY_KEY="$(sudo sed -n 's/^ *api_key: *//p' /etc/pi-print-gateway/config.yml)"
curl -H "Authorization: Bearer ${PI_GATEWAY_KEY}" \
  http://127.0.0.1:8080/api/v1/printers
```

Kết quả đúng phải có `brother_pdf`, `BROTHER_MFC` và `"available": true`.

### Máy in tem Zebra/ZPL

Khi Pi có queue Zebra thật, thêm một profile khác:

```yaml
  zebra_label:
    type: cups
    printer_name: Zebra_ZD421
    format: zpl
    raw: true
    extensions: [zpl]
    options: {}
```

Không thêm profile này nếu CUPS chưa có queue `Zebra_ZD421`, vì Odoo sẽ cảnh báo queue không sẵn sàng.

## 5. Cài và cấu hình addon trên Odoo

Restart Odoo, cập nhật Apps List và cài ứng dụng **Cổng in Pi**. Nếu chạy bằng lệnh, ví dụ:

```bash
/opt/odoo19_dev/odoo-venv/bin/python \
  /opt/odoo19_dev/odoo/odoo-bin \
  -c /opt/odoo19_dev/odoo.conf \
  -d TEN_DATABASE \
  -u pi_print_gateway,mrp_planner \
  --stop-after-init
```

Trong Odoo:

1. Mở **Cổng in Pi → Gateway in → Mới**.
2. Điền:
   - **Tên cổng in**: ví dụ `Brother_printer`.
   - **Địa chỉ Gateway**: `http://10.119.54.97:8080`.
   - **Khóa API**: API key trong `/etc/pi-print-gateway/config.yml`.
   - **Hồ sơ máy in**: `brother_pdf`.
   - **Thời gian chờ**: `30`.
   - Bỏ chọn **Xác minh chứng chỉ SSL** khi sử dụng `http://`.
3. Lưu và bấm **Kiểm tra kết nối**.
4. Mở **Thiết lập → Thiết lập chung → Cổng in Raspberry Pi**.
5. Bật **Chuyển lệnh in qua Gateway**.
6. Chọn **Gateway mặc định** là `Brother_printer`.
7. Chọn **Chỉ gửi đến Gateway** để Odoo không tải PDF xuống PDA, hoặc **Gửi đến Gateway và tải file về** nếu muốn nhận thêm bản PDF.
8. Bấm **Lưu**.

Theo dõi lịch sử tại **Cổng in Pi → Lệnh in**.

Mở một lệnh in và bấm **In lại** để gửi lại đúng PDF/ZPL đã lưu của lần in đó. Gateway tạo một lệnh mới để theo dõi riêng; lệnh cũ không bị thay đổi. Với các lệnh đã phát sinh trước khi nâng cấp module, hệ thống sẽ tạo lại PDF từ chứng từ gốc nếu có thể.

## 6. Kiểm tra và xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
| --- | --- |
| `401 Unauthorized` | API key tại Odoo không khớp với `/etc/pi-print-gateway/config.yml`. Sao chép lại key, không kèm `api_key:`. |
| CUPS queue unavailable | `printer_name` không trùng queue CUPS hoặc máy in đang tắt. Kiểm tra `lpstat -p -d`. |
| Odoo không kết nối được Pi | Kiểm tra URL/IP, route mạng, firewall TCP 8080 và `systemctl status pi-print-gateway`. |
| Odoo tải PDF thay vì in | Bật **Chuyển lệnh in qua Gateway** trong Thiết lập chung và chọn Gateway mặc định. |
| Job lỗi trên Pi | Xem `sudo journalctl -u pi-print-gateway -n 100 --no-pager` và hàng đợi `lpstat -o`. |

## 7. Phạm vi hoạt động

- Có hỗ trợ report PDF/text chuẩn `ir.actions.report` trong backend Odoo, bao gồm Odoo chạy trên PDA.
- Nếu Gateway lỗi, Odoo ghi nhận lỗi và tải report về để người dùng không mất chứng từ.
- POS receipt và liên kết PDF trực tiếp từ portal/website không đi qua backend report handler; chúng cần adapter riêng nếu muốn in qua Pi.

Tài liệu triển khai CUPS/gateway chi tiết hơn: [SERVER_SETUP.md](SERVER_SETUP.md).

# Cài Pi Print Gateway trên Raspberry Pi/Linux

Dịch vụ nhận đồng thời PDF/ZPL từ Odoo, đọc profile máy in, chọn đúng file rồi gửi qua CUPS bằng lệnh `lp`. Cùng mã nguồn có thể chạy trên Raspberry Pi hoặc máy Linux x86.

## 1. Chuẩn bị và kiểm tra CUPS

Kiểm tra queue máy in:

```bash
lpstat -p -d
```

In thử PDF:

```bash
lp -d HP_LaserJet test.pdf
```

In thử ZPL raw:

```bash
lp -d Zebra_ZD421 -o raw test.zpl
```

Tên sau `-d` là giá trị `printer_name` trong `config.yml`.

## 2. Cài server

Copy toàn bộ thư mục `pi_print_gateway` sang Pi. Trên Pi chạy:

```bash
cd pi_print_gateway
chmod +x install.sh
sudo ./install.sh
```

Installer tạo:

- ứng dụng tại `/opt/pi-print-gateway`;
- cấu hình riêng tại `/etc/pi-print-gateway/config.yml`;
- kho job tại `/var/lib/pi-print-gateway/jobs`;
- user dịch vụ `pi-print`;
- systemd service tự khởi động sau reboot;
- API key ngẫu nhiên được hiển thị một lần trên terminal.

## 3. Khai báo profile máy in

Sửa `/etc/pi-print-gateway/config.yml`:

```yaml
server:
  host: 0.0.0.0
  port: 8080
  api_key: API_KEY_DA_TAO
  max_file_size_mb: 50
  storage_dir: /var/lib/pi-print-gateway/jobs
  delete_after_submit: false

default_printer: office_pdf

printers:
  office_pdf:
    type: cups
    printer_name: HP_LaserJet
    format: pdf
    raw: false
    extensions: [pdf]
    options:
      media: A4
      fit-to-page: "true"

  zebra_label:
    type: cups
    printer_name: Zebra_ZD421
    format: zpl
    raw: true
    extensions: [zpl]
    options: {}

rules:
  - match:
      metadata:
        report_name: mrp_planner.report_manufacturing_label
    printer: zebra_label
```

- `office_pdf` và `zebra_label` là tên profile Odoo sử dụng.
- `printer_name` là queue thật trong CUPS.
- `format: pdf` khiến gateway chọn phần PDF của job.
- `format: zpl` khiến gateway chọn phần ZPL và `raw: true` truyền nguyên lệnh tới máy in.
- `options` được chuyển thành các tham số `lp -o key=value`.

Sau khi sửa:

```bash
sudo systemctl restart pi-print-gateway
sudo systemctl status pi-print-gateway
```

Xem log:

```bash
journalctl -u pi-print-gateway -f
```

## 4. Kiểm tra API

Health check:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://127.0.0.1:8080/api/v1/health
```

Danh sách profile:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://127.0.0.1:8080/api/v1/printers
```

Gửi thử cả PDF và ZPL; gateway tự chọn theo profile:

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "title=Test job" \
  -F "printer=zebra_label" \
  -F "format=auto" \
  -F "copies=1" \
  -F "pdf_file=@test.pdf;type=application/pdf" \
  -F "zpl_file=@test.zpl;type=application/vnd.zebra-zpl" \
  http://127.0.0.1:8080/api/v1/jobs
```

Response có `job_id`, `selected_format`, `printer` và trạng thái queue.

## 5. Mạng và bảo mật

- Chỉ mở TCP `8080` cho IP máy chủ Odoo; PDA không cần truy cập Pi.
- Nếu Odoo và Pi khác mạng, dùng VPN hoặc HTTPS reverse proxy.
- Không commit `/etc/pi-print-gateway/config.yml` chứa API key.
- Có thể đổi key trong `server.api_key`, sau đó restart service và cập nhật key trong Odoo.
- Đặt `delete_after_submit: true` nếu không muốn giữ file đã gửi trên Pi.

## 6. Chuyển sang Pi hoặc máy in khác

Trên máy mới: cài CUPS, copy module, chạy `install.sh`, thay `config.yml`, rồi cập nhật Gateway URL/API key trong Odoo. Không phải sửa code Odoo.

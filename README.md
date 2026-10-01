# Cổng in Raspberry Pi cho Odoo 19

Module gửi các báo cáo `qweb-pdf` và `qweb-text` từ Odoo tới một Raspberry Pi/Linux Gateway. Gateway chọn PDF hoặc ZPL theo hồ sơ máy in, rồi giao file cho CUPS để in.

Người dùng có thể bấm In bằng máy tính hoặc PDA: thiết bị chỉ kết nối tới Odoo; **Odoo server** mới là nơi gửi file tới Pi. PDA không cần cài driver, không cần truy cập Pi và không gặp CORS.

## Luồng in

```text
Máy tính / PDA → Odoo → Pi Print Gateway → CUPS → Máy in
```

Nếu đường truyền từ Odoo tới Pi bị gián đoạn, Odoo giữ nguyên PDF/ZPL đã tạo trong lệnh in, chuyển lệnh sang trạng thái **Chờ kết nối** và tự gửi lại. Người dùng không phải bấm in lần nữa:

```text
In báo cáo
  ├─ Kết nối được Pi → gửi Gateway → CUPS → máy in
  └─ Mất kết nối Pi → Chờ kết nối → cron thử lại → mạng phục hồi → gửi và in
```

Khoản retry này xử lý kết nối **Odoo → Pi Gateway**. Sau khi Gateway giao lệnh cho CUPS, việc giữ hàng đợi khi máy in mạng tắt hoặc mất kết nối do CUPS quản lý.

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

### Nâng cấp từ phiên bản cũ

Tính năng retry có thay đổi ở cả addon Odoo và ứng dụng Gateway. Sau khi cập nhật source, đồng bộ lại thư mục lên Pi và chạy installer. Cấu hình hiện có tại `/etc/pi-print-gateway/config.yml` được giữ nguyên:

```bash
rsync -avz --progress \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  /opt/odoo19_dev/odoo/Custom_addons/pi_print_gateway/ \
  pi@10.119.54.97:~/pi_print_gateway/

ssh -t pi@10.119.54.97 \
  'cd ~/pi_print_gateway && sudo ./install.sh'
```

Installer cập nhật mã nguồn và restart `pi-print-gateway`. Tiếp theo nâng cấp module Odoo để tạo các trường retry và scheduled action:

```bash
/opt/odoo19_dev/odoo-venv/bin/python \
  /opt/odoo19_dev/odoo/odoo-bin \
  -c /opt/odoo19_dev/odoo.conf \
  -d TEN_DATABASE \
  -u pi_print_gateway \
  --stop-after-init
```

Sau đó restart service Odoo đang chạy. Trong chế độ developer có thể kiểm tra scheduled action tại **Thiết lập → Kỹ thuật → Tự động hóa → Tác vụ đã lên lịch**, tên **Pi Print Gateway: gửi lại lệnh chờ kết nối**.

## 6. Cơ chế chờ mạng và tự gửi lại

### Khi nào lệnh được đưa vào hàng chờ

Odoo chỉ đưa lệnh vào trạng thái **Chờ kết nối** khi HTTP request gặp lỗi kết nối hoặc timeout, ví dụ:

- Pi đang tắt hoặc đang khởi động lại;
- cáp mạng/Wi-Fi bị mất;
- không route được tới mạng của Pi;
- cổng 8080 tạm thời không phản hồi;
- request vượt quá thời gian chờ đã cấu hình.

Các lỗi cấu hình không được retry tự động, vì retry sẽ không tự khắc phục được nguyên nhân:

- `401 Unauthorized`: sai API key;
- `400 Unknown printer profile`: sai tên profile;
- `422`: thiếu đúng định dạng PDF/ZPL;
- lỗi xác minh chứng chỉ SSL;
- Gateway/CUPS trả lỗi HTTP khác.

Những trường hợp này chuyển sang **Có lỗi** để quản trị viên xử lý.

### Lịch thử lại

Scheduled action chạy mỗi phút và lấy tối đa 10 lệnh đến hạn. Timeout kết nối cho mỗi lần thử được giới hạn tối đa 5 giây; thời gian chờ phản hồi vẫn dùng giá trị cấu hình trên Gateway. Mỗi lệnh áp dụng backoff để không tạo tải liên tục khi Pi mất mạng lâu:

| Lần lỗi liên tiếp | Chờ trước lần kế tiếp |
| ---: | ---: |
| 1 | 1 phút |
| 2 | 2 phút |
| 3 | 4 phút |
| 4 | 8 phút |
| 5 trở đi | 15 phút |

Hệ thống tiếp tục thử lại không giới hạn cho tới khi:

- gửi thành công và chuyển sang **Đã gửi đến Gateway**;
- Gateway bị vô hiệu hóa;
- file PDF/ZPL đã lưu không còn tồn tại;
- Gateway trả về lỗi không phải lỗi mạng.

Trong màn hình chi tiết lệnh in có thể xem **Số lần thử lại**, **Thử lại lúc**, **Lần gửi gần nhất** và thông báo lỗi gần nhất. Nút **Gửi lại ngay** cho phép bỏ qua thời gian chờ hiện tại.

### Chống in trùng khi timeout

Mỗi lần retry dùng lại cùng `source_job_id` là ID lệnh in trong Odoo. Trong khi Gateway vẫn đang chạy, nếu request đầu tiên đã được nhận nhưng response bị mất do timeout, Gateway nhận diện lần gửi lại và trả về job đã có thay vì tạo thêm một lệnh CUPS.

Không bấm **In lại** cho một lệnh đang ở trạng thái **Chờ kết nối**, vì **In lại** có chủ đích tạo một lệnh mới và có thể dẫn tới hai bản in khi mạng phục hồi. Hãy dùng **Gửi lại ngay** nếu cần kiểm tra kết nối lập tức.

## 7. Kiểm tra và xử lý lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
| --- | --- |
| `401 Unauthorized` | API key tại Odoo không khớp với `/etc/pi-print-gateway/config.yml`. Sao chép lại key, không kèm `api_key:`. |
| CUPS queue unavailable | `printer_name` không trùng queue CUPS hoặc máy in đang tắt. Kiểm tra `lpstat -p -d`. |
| Odoo không kết nối được Pi | Kiểm tra URL/IP, route mạng, firewall TCP 8080 và `systemctl status pi-print-gateway`. |
| Lệnh ở `Chờ kết nối` | Đây là trạng thái bình thường khi mất mạng. Kiểm tra cột **Thử lại lúc** hoặc bấm **Gửi lại ngay** sau khi mạng phục hồi. |
| Mạng đã có nhưng lệnh chưa chạy ngay | Scheduled action chạy mỗi phút và lệnh còn tuân theo backoff. Bấm **Gửi lại ngay** nếu cần in tức thời. |
| Lệnh chuyển từ `Chờ kết nối` sang `Có lỗi` | Odoo đã kết nối lại được Pi nhưng Gateway trả lỗi cấu hình/CUPS. Mở lệnh để xem **Phản hồi từ Gateway**. |
| Odoo tải PDF thay vì in | Bật **Chuyển lệnh in qua Gateway** trong Thiết lập chung và chọn Gateway mặc định. |
| Job lỗi trên Pi | Xem `sudo journalctl -u pi-print-gateway -n 100 --no-pager` và hàng đợi `lpstat -o`. |

## 8. Vận hành và giám sát

Kiểm tra các lệnh đang chờ trong Odoo bằng menu **Cổng in Pi → Lệnh in**, lọc trạng thái **Chờ kết nối**. Trên Pi dùng:

```bash
sudo systemctl status pi-print-gateway --no-pager
sudo journalctl -u pi-print-gateway -n 100 --no-pager
lpstat -p -d
lpstat -o
```

Sau khi mạng phục hồi, không cần restart Gateway hoặc Odoo. Scheduled action sẽ tự gửi lại. Nếu cần xác nhận ngay, bấm **Gửi lại ngay** trên lệnh chờ.

Các file chờ nằm trong attachment của Odoo, vì vậy phải đưa filestore Odoo vào quy trình backup. Không xóa attachment của `pi.print.job` đang chờ.

## 9. Phạm vi hoạt động

- Có hỗ trợ report PDF/text chuẩn `ir.actions.report` trong backend Odoo, bao gồm Odoo chạy trên PDA.
- Nếu mất kết nối Gateway, Odoo lưu lệnh để tự gửi lại; chỉ tải thêm report khi công ty chọn **Gửi đến Gateway và tải file về**.
- Retry không thay thế hàng đợi CUPS. Trạng thái máy in sau khi CUPS đã nhận job được quản lý bằng `lpstat`, giao diện CUPS hoặc driver máy in.
- POS receipt và liên kết PDF trực tiếp từ portal/website không đi qua backend report handler; chúng cần adapter riêng nếu muốn in qua Pi.

Tài liệu triển khai CUPS/gateway chi tiết hơn: [SERVER_SETUP.md](SERVER_SETUP.md).

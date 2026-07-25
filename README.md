# 🛡️ Python Guard Web

Web version của tool đóng gói & mã hoá Python. Có giao diện hiện đại, login, và REST API để client khác (PHP, Node, curl…) gọi vào.

## Deploy lên Render (2 phút)

1. Đẩy code lên GitHub (hoặc upload zip này).
2. Vào https://dashboard.render.com → **New +** → **Web Service** → chọn repo.
3. Render sẽ đọc `render.yaml` và tự cấu hình. Nếu tạo tay:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Vào tab **Environment** đổi:
   - `ADMIN_USER`, `ADMIN_PASS` (đăng nhập web)
   - `API_TOKEN` (dùng cho PHP client)
   - `SECRET_KEY` (bất kỳ chuỗi dài)

Sau khi deploy xong bạn sẽ có URL dạng `https://python-guard-web.onrender.com`.

## Tính năng

- 🔐 Trang login đẹp, dark theme
- 📤 Upload file `.py` → mã hoá bằng **PyArmor** → tải về ZIP
- ⚙️ Tuỳ chọn mức bảo vệ (low / medium / high) + mã hoá chuỗi
- 🔑 REST API có Bearer token cho tích hợp bên ngoài
- 📊 Xem lịch sử job

## API

Header bắt buộc: `Authorization: Bearer <API_TOKEN>`

| Method | Path                     | Mô tả                             |
|--------|--------------------------|-----------------------------------|
| POST   | `/api/obfuscate`         | multipart: `file`, `app_name`, `level`, `obfuscate_strings` |
| GET    | `/api/status/{job_id}`   | Trạng thái job                    |
| GET    | `/api/download/{job_id}` | Tải file ZIP đã mã hoá            |
| GET    | `/api/jobs`              | 50 job gần nhất                   |
| GET    | `/health`                | Health check                      |

## Test nhanh (curl)

```bash
curl -F file=@main.py -F app_name=MyApp -F level=high \
  -H "Authorization: Bearer $API_TOKEN" \
  https://<your>.onrender.com/api/obfuscate
```

## Ghi chú về `.exe`

Render chạy Linux nên không thể build trực tiếp `.exe` Windows.
Server trả về **source đã mã hoá bằng PyArmor** (chạy được ngay bằng Python).
Muốn ra `.exe` thì chạy PyInstaller trên máy Windows với source đã mã hoá:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name MyApp main.py
```

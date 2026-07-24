# TIENDEV Buff Panel

Buff TikTok tự động qua Zefoy, **không cần cookie / user-agent** do người
dùng nhập. Logic buff lấy từ `buff.py` (v3.0.3 của TIENDEV), bọc thành
FastAPI + giao diện web hiện đại, deploy 1 phát lên Render / Railway /
Docker.

## Tính năng

- Session tự khởi tạo (`PHPSESSID` tự lấy).
- Tự tải ảnh captcha, tự giải bằng OCR (Tesseract). Fallback nhập tay.
- Danh sách dịch vụ auto lấy từ trang chủ Zefoy.
- Tự pick giới hạn tối đa của `<select>` mỗi lượt buff.
- Auto decode phản hồi `base64-reversed` của Zefoy.
- Web UI tối, gọn, mobile-friendly. Có lặp / dừng / đếm cooldown.

## Cấu trúc

```
tiendev_buff/
├─ app.py               # FastAPI entrypoint
├─ app/
│  ├─ __init__.py
│  ├─ buff_core.py      # Logic buff.py (decode, captcha, services, do_buff_once)
│  └─ ocr_solver.py     # Tự giải captcha bằng pytesseract
├─ static/index.html    # Web UI
├─ requirements.txt
├─ runtime.txt
├─ Procfile             # Heroku/Railway
├─ render.yaml          # Render.com
├─ Dockerfile           # Docker/Fly.io/Cloud Run
└─ README.md
```

## Chạy local

```bash
cd tiendev_buff
pip install -r requirements.txt
# Cài tesseract (cần cho OCR)
#   Ubuntu:  sudo apt install tesseract-ocr
#   macOS:   brew install tesseract
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki
python app.py
# mở http://localhost:8000
```

## Deploy Render (khuyến nghị Docker)

Render free plan **không apt-install được**, nên OCR có thể fail. Cách chắc:
chọn **Docker** khi tạo service, Render tự build `Dockerfile` (đã kèm
tesseract). Nếu OCR fail thì UI tự chuyển sang nhập tay, không sập.

## API

| Endpoint | Body | Mô tả |
|---|---|---|
| POST `/api/start` | `{}` | Tạo session, trả `session_id` + `captcha_b64` |
| POST `/api/refresh_captcha` | `{session_id}` | Lấy ảnh captcha khác |
| POST `/api/auto_solve` | `{session_id}` | OCR tự giải + submit |
| POST `/api/solve` | `{session_id, answer}` | Submit captcha thủ công |
| POST `/api/services` | `{session_id}` | Load lại danh sách dịch vụ |
| POST `/api/run` | `{session_id, service, url}` | Chạy 1 lượt buff |

## Xoá nhanh

Tất cả nằm trong 1 folder `tiendev_buff/`. Lỗi → `rm -rf tiendev_buff`,
xong.

> Made by **TIENDEV** — Bản quyền thuộc về TIENDEV. Tool dùng cho mục đích
> học tập; người dùng chịu trách nhiệm với Term of Service của Zefoy/TikTok.
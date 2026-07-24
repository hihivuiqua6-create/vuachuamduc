# Buff API (Zefoy) - Deploy Render

## Deploy nhanh
1. Fork/upload repo này lên GitHub.
2. Vào https://render.com → New → Web Service → chọn repo.
3. Render sẽ tự đọc `render.yaml`:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -w 1 -k gthread --threads 8 -t 120 -b 0.0.0.0:$PORT app:app`
4. Env vars (tuỳ chọn):
   - `ADMIN_KEY` — mặc định `mducdeptrai`
   - `TELEGRAM_BOT_TOKEN` — token bot Telegram (nếu muốn bật bot)
   - `PUBLIC_BASE_URL` — URL Render của bạn, vd `https://buff-api.onrender.com`

## Sử dụng
- Trang chủ: hiển thị link API + hướng dẫn + phần Telegram bot
- `/admin` (key: `mducdeptrai`): thêm cookie Zefoy + user-agent
- API (không cần key):
  - `GET /api/services` → list dịch vụ đang bật
  - `POST /api/buff` (JSON `{service, url}`) → thực thi 1 lượt buff

## Telegram bot
- User `/start` → bot yêu cầu bấm link verify (mở web admin public)
- Sau verify, được `/buff <service> <url>` — tối đa **10 lượt / ngày**
- Cookie & UA admin add trên web, bot không cần add gì thêm

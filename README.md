# TienBuff

FastAPI backend + SPA cho TikTok Zefoy buffing.

## Cấu trúc

```
tienbuff/
  main.py               # Entrypoint (uvicorn main:app)
  src/
    api.py              # FastAPI routes (mount tại /api)
    auth.py             # JWT + bcrypt
    storage.py          # JSON file storage
    zefoy_core.py       # Logic Zefoy
  static/
    index.html          # SPA (login/register + dashboard + admin)
  requirements.txt
  render.yaml
  runtime.txt           # python-3.12.7
  .python-version       # 3.12.7
  Procfile
```

## Deploy Render

1. Push repo lên GitHub.
2. Trên Render tạo **Web Service**, chọn repo.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Env vars đã có sẵn trong `render.yaml`.

Vào link Render → trang đăng ký hiện đại sẽ hiện ra.

## Luật

- **Người đăng ký đầu tiên = ADMIN**. Sau đó đăng ký bị đóng.
- Admin thêm cookie + user-agent Zefoy trong tab Admin.
- Chỉ user đã login mới gọi được `/api/services` và `/api/run`.

## Endpoint

- `GET  /api/status`
- `POST /api/register` (chỉ dùng được 1 lần đầu)
- `POST /api/login`
- `GET  /api/me`
- `GET  /api/services`
- `POST /api/run`
- `GET  /api/admin/cookies`
- `POST /api/admin/cookies`
- `DELETE /api/admin/cookies/{id}`
- `POST /api/admin/cookies/{id}/toggle`
- `GET  /api/admin/history`
- `DELETE /api/admin/reset-users`

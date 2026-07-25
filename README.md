# Zefoy Buff Web API (Render-ready)

Chuyển tool desktop (Tkinter) thành **web service** deploy trên Render, có:
- Giao diện web hiện đại (login + dashboard) — Tailwind qua CDN.
- REST API JSON để client ngoài (PHP, Node, Python…) gọi tới.
- Đăng nhập bằng **KEY** xác thực qua Firebase Realtime DB (giữ nguyên hệ thống gốc).

## Cấu trúc
```
render_api/
├─ app.py             # Flask app (routes + API)
├─ zefoy_core.py      # ZefoyClient + FirebaseManager (đã tách khỏi Tkinter)
├─ templates/
│   ├─ login.html
│   └─ dashboard.html
├─ static/style.css
├─ requirements.txt
├─ Procfile
├─ render.yaml
└─ runtime.txt
```

## Deploy Render

1. Push thư mục này lên GitHub.
2. Vào https://dashboard.render.com → **New +** → **Web Service** → connect repo.
3. Điền các trường (hoặc để `render.yaml` tự nhận):

| Field         | Value                                                                              |
| ------------- | ---------------------------------------------------------------------------------- |
| Environment   | `Python 3`                                                                         |
| **Build Command** | `pip install -r requirements.txt`                                              |
| **Start Command** | `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT` |
| Env Var       | `SECRET_KEY` = (random 32+ ký tự, hoặc để Render generate)                         |

4. Deploy. URL của bạn sẽ là `https://<tên-service>.onrender.com`.

## REST API

Tất cả endpoint (trừ `/api/login`, `/api/health`) yêu cầu cookie session sau khi login.

| Method | Path              | Body                          | Mô tả                       |
| ------ | ----------------- | ----------------------------- | --------------------------- |
| POST   | `/api/login`      | `{"key":"..."}`               | Login bằng KEY Firebase     |
| POST   | `/api/logout`     | —                             | Logout                      |
| GET    | `/api/me`         | —                             | Thông tin user hiện tại     |
| POST   | `/api/init`       | —                             | Khởi tạo phiên Zefoy        |
| GET    | `/api/captcha`    | `?format=image` hoặc mặc định | Lấy captcha (base64 / png)  |
| POST   | `/api/solve`      | `{"answer":"..."}`            | Giải captcha                |
| GET    | `/api/services`   | —                             | Danh sách dịch vụ           |
| POST   | `/api/buff`       | `{"service":"...","url":"..."}` | Thực hiện buff            |
| GET    | `/api/health`     | —                             | Healthcheck                 |

## Local run
```bash
pip install -r requirements.txt
python app.py
# → http://localhost:10000
```

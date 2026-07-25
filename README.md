# Zefoy Buff Web API v2 — MMO Edition

Nâng cấp từ bản gốc:
- Giao diện MMO/cyberpunk với neon glow, hex badge, scanlines, loading orb.
- **Background buff worker per-key**: mỗi KEY chạy 1 thread nền riêng, tắt trình duyệt vẫn tiếp tục xử lý job.
- **Realtime job stream** qua SSE (`/api/stream`).
- Rate limit chống spam login/buff.
- Session cookie HttpOnly, SameSite=Lax, hỗ trợ Secure qua env `COOKIE_SECURE=1`.

## Deploy Render
Same as trước: push repo, chọn Web Service, giữ `render.yaml`.

## Endpoint mới
- `POST /api/buff` — body `{service, url, loops(1-500)}`, đẩy job vào queue của KEY.
- `GET  /api/jobs` — danh sách job của KEY hiện tại.
- `POST /api/jobs/clear` — xoá lịch sử job.
- `GET  /api/stream` — SSE realtime.

## Ghi chú "treo buff"
Worker sống theo tiến trình Flask, không phụ thuộc browser. Free tier Render sẽ **sleep** khi không có request 15 phút → worker bị dừng. Muốn thật sự "treo 24/7", dùng Render **Starter plan** (không sleep), hoặc self-host VPS.

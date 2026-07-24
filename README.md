# TienBuff v3

Panel buff TikTok qua Zefoy với FastAPI + Telegram bot.

## Tính năng

- Đăng ký / đăng nhập JWT (người đầu tiên = admin)
- Admin quản lý pool cookie + user-agent Zefoy
- Chọn dịch vụ bằng combobox (Views, Hearts, Followers…) tự load từ Zefoy
- **Telegram bot** (admin cấu hình token qua web):
  - Kiểm tra user đã join nhóm bắt buộc
  - Lệnh: `/start`, `/link <mã>`, `/status`, `/help`
- **Free user** giới hạn 10 lần/ngày (đổi bằng env `FREE_DAILY_LIMIT`)
- History + stats

## Chạy local

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Mở http://localhost:8000

## Deploy Render

Push repo lên GitHub → Render → **New Web Service** → Connect repo → giữ nguyên
`render.yaml`. Render sẽ tự đọc.

`JWT_SECRET` được Render tự sinh. `DATA_DIR=/tmp/tienbuff_data` (Render free
chỉ có disk ephemeral — nếu muốn giữ dữ liệu qua deploy cần Persistent Disk).

## Cấu hình sau khi deploy

1. Truy cập site, đăng ký → tài khoản đầu tiên = **admin**.
2. Vào tab **Cookie** → thêm cookie Zefoy + user-agent trình duyệt của bạn.
3. Vào tab **Telegram**:
   - Dán bot token (lấy từ [@BotFather](https://t.me/BotFather)).
   - Thêm bot vào nhóm của bạn, cấp quyền admin (để `getChatMember` hoạt động).
   - Dán `chat_id` nhóm (dùng bot [@RawDataBot](https://t.me/RawDataBot) hoặc
     `getUpdates` để lấy — dạng `-1001234567890`).
   - Dán link nhóm `https://t.me/…`.
   - Bật **Require join** để bắt buộc user free join nhóm.
4. User đăng ký → tab **Buff**: bấm **Lấy mã liên kết** → gửi
   `/link MÃ` cho bot → bấm **Kiểm tra** → chọn dịch vụ → buff.

## Env vars

| Var | Mặc định | Ý nghĩa |
|---|---|---|
| `JWT_SECRET` | `change-me…` | Bí mật ký JWT |
| `DATA_DIR` | `./data` | Nơi lưu `db.json` |
| `FREE_DAILY_LIMIT` | `10` | Số lần buff free / ngày / user |
| `PORT` | `8000` | Port |

## Ghi chú

- Bot chạy long-polling trong background thread (đơn giản, không cần webhook).
- Trên Render free, service ngủ sau ~15 phút không traffic → bot cũng ngủ theo.
  Muốn 24/7 phải nâng plan hoặc dùng cron ping.
- Buff view TikTok qua Zefoy vi phạm ToS TikTok. Bạn tự chịu trách nhiệm.
"""JWT auth. Người đăng ký đầu tiên = admin. Sau đó khoá đăng ký."""
import os
import time
import bcrypt
import jwt
from fastapi import Header, HTTPException

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-super-secret-key-please")
JWT_ALG = "HS256"
JWT_TTL = 60 * 60 * 24  # 24h


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def make_token(sub: str, role: str) -> str:
    payload = {"sub": sub, "role": role,
               "exp": int(time.time()) + JWT_TTL,
               "iat": int(time.time())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token hết hạn, đăng nhập lại")
    except Exception:
        raise HTTPException(401, "Token không hợp lệ")


def _extract(auth: str | None) -> dict:
    if not auth:
        raise HTTPException(401, "Thiếu token")
    if auth.lower().startswith("bearer "):
        auth = auth[7:].strip()
    return decode_token(auth)


def require_user(authorization: str | None = Header(None)) -> dict:
    return _extract(authorization)


def require_admin(authorization: str | None = Header(None)) -> dict:
    p = _extract(authorization)
    if p.get("role") != "admin":
        raise HTTPException(403, "Yêu cầu quyền admin")
    return p

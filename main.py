# Entrypoint shim so `gunicorn main:app` / `uvicorn main:app` works out of the box.
from app import app  # noqa: F401

# Alias /api/run -> /api/obfuscate for clients that use the older path.
from app import api_obfuscate
app.post("/api/run")(api_obfuscate)

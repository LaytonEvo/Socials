# ${PORT:-8080} rather than $PORT: an unset PORT makes uvicorn exit 2 with
# "Option '--port' requires an argument", which reads like a crash rather than a
# missing variable. Railway sets PORT, so the fallback should never be used.
web: python -m uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}

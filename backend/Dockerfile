FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# pyzbar wraps the native zbar C library; libzbar0 provides it on Debian.
# Without it, `import pyzbar` fails at runtime (missing libzbar.so).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application code and the assets the entrypoint/migrations need.
COPY app ./app
COPY static ./static
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY entrypoint.sh ./

# Strip any CRLF (file may be authored on Windows) and make it runnable.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Render injects $PORT at runtime; this is just documentation/local default.
EXPOSE 8124

CMD ["./entrypoint.sh"]

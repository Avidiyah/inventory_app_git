FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# The deploy hook rebuilds this image but does not synchronize render.yaml into an
# existing Render service. Keep the hosted NetFacilities capability enabled in the
# image itself so a normal gated deploy cannot silently fall back to "disabled".
# The authentication state remains an operator-provisioned Render Secret File; a
# missing/expired file reports not_authenticated rather than exposing or inventing
# credentials. Runtime environment values can still override either default.
ENV NETFACILITIES_ENABLED=true \
    NETFACILITIES_STORAGE_STATE_PATH=/etc/secrets/netfacilities-storage-state.json

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

# Drop root. Nothing needs write access at runtime: the app only reads
# `static/`, PYTHONDONTWRITEBYTECODE (set above) stops .pyc writes, and
# `alembic upgrade head` writes to Postgres rather than to disk. The
# build-time steps above still run as root, so package install and the
# chmod are unaffected.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Render injects $PORT at runtime; this is just documentation/local default.
EXPOSE 8124

CMD ["./entrypoint.sh"]

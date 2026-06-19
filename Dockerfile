# S1-Episode funding trader — production image.
FROM python:3.12-slim

# Flush stdout/stderr immediately so `docker logs` is live; no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# CA certificates for TLS to MEXC (slim base may not include them).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY . .

# Normalize the entrypoint line endings (repo may carry CRLF from Windows) + make runnable.
RUN sed -i 's/\r$//' deploy/entrypoint.sh && chmod +x deploy/entrypoint.sh

# Run unprivileged; state/ and logs/ are mount points owned by this user.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/state /app/logs \
    && chown -R app:app /app
USER app

# Default mode is paper (config.yaml). Live requires runtime.mode: live AND FRT_CONFIRM_LIVE=1.
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["trade"]

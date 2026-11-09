# WIOT Platform v2 — production image
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN useradd --system --uid 10001 --home /app wiot
COPY pyproject.toml README.md ./
COPY wiot ./wiot
RUN pip install ".[analytics]"
ENV WIOT_HOST=0.0.0.0 WIOT_PORT=8000 WIOT_DATA_DIR=/data WIOT_LOG_JSON=true
RUN mkdir -p /data && chown wiot /data
VOLUME ["/data"]
USER wiot
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "-m", "wiot", "serve"]

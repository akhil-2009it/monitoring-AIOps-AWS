# Anomaly Scoring API — runs on EKS, port 8087.
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8087

WORKDIR /app

COPY api/scoring/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY ml/   /app/ml/
COPY api/  /app/api/

RUN useradd --create-home --shell /bin/false appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8087

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8087/health').status==200 else 1)"

CMD ["uvicorn", "api.scoring.main:app", "--host", "0.0.0.0", "--port", "8087", "--workers", "2"]

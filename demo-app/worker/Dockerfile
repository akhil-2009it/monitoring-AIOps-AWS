FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY app /app/app

RUN useradd --create-home --shell /bin/false appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

CMD ["python", "-m", "app.worker"]

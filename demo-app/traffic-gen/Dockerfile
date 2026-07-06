FROM python:3.11-slim
RUN pip install --no-cache-dir locust==2.30.0
COPY locustfile.py /app/locustfile.py
WORKDIR /app

# Defaults for headless run; override via CMD
ENV DEMO_MODE=normal
ENV DEMO_ATTACK=ddos

CMD ["locust", "-f", "/app/locustfile.py", "--headless", "--users", "20", "--spawn-rate", "2", "--run-time", "1h"]

FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY services/ewelink-callback/main.py /app/main.py
COPY services/ewelink-callback/collector.py /app/collector.py
USER 10001:10001
EXPOSE 8765
CMD ["python", "/app/main.py"]

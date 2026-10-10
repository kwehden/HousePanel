FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/weather-poller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/weather-poller/src/ src/
CMD ["python", "-m", "weather_poller.main"]

FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/calendar-poller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/calendar-poller/src/ src/
CMD ["uvicorn", "calendar_poller.main:app", "--host", "0.0.0.0", "--port", "8003"]

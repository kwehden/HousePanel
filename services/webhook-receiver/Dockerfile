FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/webhook-receiver/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/webhook-receiver/src/ src/
CMD ["uvicorn", "webhook_receiver.main:app", "--host", "0.0.0.0", "--port", "8000"]

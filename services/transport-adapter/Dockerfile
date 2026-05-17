FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/transport-adapter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/transport-adapter/src/ src/
CMD ["uvicorn", "transport_adapter.main:app", "--host", "0.0.0.0", "--port", "8002"]

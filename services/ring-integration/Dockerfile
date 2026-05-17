FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/ring-integration/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ring-integration/src/ src/
CMD ["python", "-m", "ring_integration.main"]

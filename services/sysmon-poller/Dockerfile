FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/src
COPY services/shared/ ./shared/
RUN pip install --no-cache-dir ./shared/
COPY services/sysmon-poller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/sysmon-poller/src/ src/
CMD ["python", "-m", "sysmon_poller.main"]

FROM python:3.10-slim

WORKDIR /app
COPY pythonkni /app/pythonkni
COPY scripts/verify_wifi_audit_report.py /app/verify_wifi_audit_report.py

ENTRYPOINT ["python", "/app/verify_wifi_audit_report.py"]

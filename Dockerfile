FROM python:3.12-slim

# Never write .pyc, always flush logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HBD_DATA=/data/cohort_football_100.csv \
    HBD_OUTPUT=/output \
    HBD_TZ=Africa/Tunis \
    TZ=Africa/Tunis

WORKDIR /opt/hbd

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ core/
COPY app/ app/

# Seed data is baked into the image; docker-compose mounts a volume over /data
# so check-ins persist across restarts.
COPY data/ /data/
RUN mkdir -p /output

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

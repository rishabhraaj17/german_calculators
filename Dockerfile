FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY public /app/public

# Test stage: runs the full suite (golden vectors from the official calculator
# and BMF reference results). `docker compose run --rm test`
FROM base AS test
COPY backend/requirements-dev.txt backend/pytest.ini ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY backend/tests ./tests
CMD ["python", "-m", "pytest", "-q"]

FROM base AS app
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

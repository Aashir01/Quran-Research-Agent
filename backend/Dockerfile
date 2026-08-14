FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY qra ./qra
RUN pip install --no-cache-dir -e .
EXPOSE 8000
CMD ["uvicorn", "qra.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

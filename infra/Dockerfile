FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY aegis ./aegis
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps .
COPY infra ./infra
COPY scripts ./scripts
CMD ["uvicorn","aegis.api:app","--host","0.0.0.0","--port","8000"]

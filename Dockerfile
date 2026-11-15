# Ember API + static frontend (Render, Cloud Run or any container host).
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY pipeline pipeline
COPY backend backend
COPY frontend frontend
COPY data/processed data/processed
ENV PYTHONPATH=/app/backend:/app/pipeline PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn ember_api.main:app --host 0.0.0.0 --port ${PORT}"]

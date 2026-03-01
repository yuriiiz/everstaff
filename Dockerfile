# Stage 1: Build frontend
FROM node:20-slim AS web-builder
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Build and run Python app
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
COPY agents/ agents/
COPY skills/ skills/
COPY tools/ tools/
COPY --from=web-builder /app/web/dist src/agent_os/web_static/
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "agent_os.server:app", "--host", "0.0.0.0", "--port", "8000"]

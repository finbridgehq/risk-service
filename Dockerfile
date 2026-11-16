# Etapa 1: instala las dependencias con uv, sin las de desarrollo.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev
COPY . .

# Etapa 2: imagen final, sin uv y con un usuario sin privilegios.
FROM python:3.12-slim
# curl, para el healthcheck del compose (como en los demás servicios).
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN groupadd --system risk && useradd --system --gid risk --no-create-home risk
WORKDIR /app
COPY --from=build --chown=risk:risk /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER risk
EXPOSE 8000
# Aplica las migraciones y arranca con UN solo worker: el consumidor de Kafka y el
# repartidor viven en este proceso. Se escala con más contenedores, no con --workers.
CMD ["sh", "-c", "alembic upgrade head && exec fastapi run main.py --host 0.0.0.0 --port 8000 --workers 1"]

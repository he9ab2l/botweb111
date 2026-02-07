# syntax=docker/dockerfile:1

# Build the fanfan WebUI assets
FROM node:20-bookworm-slim AS ui
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY frontend/ frontend/
RUN mkdir -p nanobot/web/static
RUN cd frontend && npm run build


# Runtime
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime
WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot

# Copy source
COPY nanobot/ nanobot/

# Copy built UI
COPY --from=ui /app/nanobot/web/static/dist nanobot/web/static/dist

# Install the project (scripts, package metadata)
RUN uv pip install --system --no-cache .

EXPOSE 4096
ENV FANFAN_UI_MODE=static

CMD ["python", "-m", "uvicorn", "nanobot.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "4096", "--log-level", "info"]

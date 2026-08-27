# ── Stage 1: build the Vue dashboard (/app) and sandbox (/test) ─────────────
# Produces index.html -> /app and test.html -> /test, served by FastAPI.
FROM node:20-alpine AS frontend

WORKDIR /build

# Install JS deps first for layer-cache reuse, then copy source and build.
COPY src/NZMealOptimiser/web/frontend/package.json src/NZMealOptimiser/web/frontend/package-lock.json ./
RUN npm ci
COPY src/NZMealOptimiser/web/frontend/ ./
# --dest overrides vue.config.js outputDir so the path is build-stage-local.
RUN npm run build --dest /build/dist

# ── Stage 2: Python runtime ─────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install root requirements first (layer cache for Python deps).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the NZMealOptimiser package (src-layout).
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Overlay the freshly built Vue assets (replaces any stale committed output).
COPY --from=frontend /build/dist/ ./src/NZMealOptimiser/web/static/vue/

# Shared data + docs: data/ holds stores/dishes; docs/technical/ backs /tech-docs.
COPY data/ ./data/
COPY docs/ ./docs/
COPY AGENTS.md ./AGENTS.md

EXPOSE 8000

CMD ["uvicorn", "NZMealOptimiser.web.main:app", "--host", "0.0.0.0", "--port", "8000"]

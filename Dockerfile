# ── Stage 1: build the Vue dashboard (/app) and sandbox (/test) ─────────────
# Produces index.html -> /app and test.html -> /test, served by FastAPI.
FROM node:20-alpine AS frontend

# Stage root is /src so the vue.config.js `outputDir: '../static/vue'` resolves
# to /src/NZMealOptimiser/web/static/vue (the same path the python stage copies).
WORKDIR /src

# Install JS deps first for layer-cache reuse. COPY targets the same relative
# path as the eventual WORKDIR so vue-cli-service finds the source tree.
COPY src/NZMealOptimiser/web/frontend/package.json src/NZMealOptimiser/web/frontend/package-lock.json ./NZMealOptimiser/web/frontend/
WORKDIR /src/NZMealOptimiser/web/frontend
RUN npm ci
COPY src/NZMealOptimiser/web/frontend/ ./
# No --dest flag: vue.config.js outputDir is the single source of truth.
RUN npm run build

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
COPY --from=frontend /src/NZMealOptimiser/web/static/vue/ ./src/NZMealOptimiser/web/static/vue/

# Shared data + docs: data/ holds stores/dishes; docs/technical/ backs /tech-docs.
COPY data/ ./data/
COPY docs/ ./docs/
COPY AGENTS.md ./AGENTS.md

EXPOSE 8000

CMD ["uvicorn", "NZMealOptimiser.web.main:app", "--host", "0.0.0.0", "--port", "8000"]

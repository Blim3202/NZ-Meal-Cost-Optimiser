FROM python:3.12-slim

WORKDIR /app

# Install root requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the NZMealOptimiser package (src-layout)
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Copy data + docs (shared resources at repo root)
COPY data/ ./data/
COPY AGENTS.md ./AGENTS.md

EXPOSE 8000

CMD ["uvicorn", "NZMealOptimiser.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
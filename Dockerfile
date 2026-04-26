FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir uv && uv pip install --system -e ".[dev]"

COPY . .

ENTRYPOINT ["pulse"]

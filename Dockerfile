FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && uv pip install --system -e ".[dev]"

COPY . .

ENTRYPOINT ["pulse"]

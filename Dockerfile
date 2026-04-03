# Use a slim Python base image
FROM python:3.12-slim AS builder

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Enable bytecode compilation and copy dependency files
ENV UV_COMPILE_BYTECODE=1
ENV UV_HTTP_TIMEOUT=300
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN uv sync --frozen --no-install-project --no-dev

# --- Final Stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Ensure the app uses the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Copy the rest of your Django project code
COPY . .

# Set environment variables for production
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=core.settings

# Expose the port (AWS ECS default is often 8000 or 80)
EXPOSE 8000

# Start the app with Uvicorn (ASGI) for your async views
CMD ["uvicorn", "core.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
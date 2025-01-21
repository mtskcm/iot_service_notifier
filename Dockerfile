# Use a lightweight Python base image
FROM python:3.9-slim

# Create a non-root user
RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid 1000 --no-create-home appuser

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src /app/src

# Change to non-root user
USER appuser

# Set the environment variable for the .env file
ENV PYDANTIC_ENV_FILE=/app/src/local.env

# Command to start the application
CMD ["python", "/app/src/main.py"]

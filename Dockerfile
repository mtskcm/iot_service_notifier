FROM python:3.9-slim

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid 1000 --no-create-home appuser

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src

USER appuser

ENV PYDANTIC_ENV_FILE=/app/src/local.env

CMD ["python", "/app/src/main.py"]

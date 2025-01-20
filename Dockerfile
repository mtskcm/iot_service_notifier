FROM python:3.13-slim

RUN pip install apprise loguru paho-mqtt pydantic pydantic-settings

COPY src/ /app

WORKDIR /app

CMD { "/usr/bin/env", "python3", "main.py" }
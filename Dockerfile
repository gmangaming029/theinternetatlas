FROM python:3.12-slim

WORKDIR /app

COPY . .

ENV PYTHONUNBUFFERED=1
ENV ATLAS_DATABASE_PATH=/app/data/atlas.db

EXPOSE 8100

VOLUME ["/app/data"]

CMD ["python", "main.py"]
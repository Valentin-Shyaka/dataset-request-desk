FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
# dev requirements included so `docker compose run api pytest` works; a production image would skip them
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["sh", "start.sh"]

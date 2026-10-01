.PHONY: up down test logs

up:
	docker compose up --build

down:
	docker compose down

test:
	docker compose up -d db
	docker compose run --rm --build -e DATABASE_URL=postgresql+psycopg://drd:drd@db:5432/drd_test api pytest -p no:cacheprovider

logs:
	docker compose logs -f api

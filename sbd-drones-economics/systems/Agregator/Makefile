.PHONY: help build test docker-up docker-up-dev docker-down docker-logs

help:
	@echo "make build       - build gateway binary"
	@echo "make test        - run Go tests"
	@echo "make docker-up   - start postgres + aggregator via docker compose kafka profile"
	@echo "make docker-up-dev - start local dev stack with kafka"
	@echo "make docker-down - stop docker compose services"
	@echo "make docker-logs - follow service logs"

build:
	go build -o bin/agregator ./src/gateway

test:
	go test ./...

docker-up:
	docker compose --profile kafka up -d --build

docker-up-dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile kafka up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

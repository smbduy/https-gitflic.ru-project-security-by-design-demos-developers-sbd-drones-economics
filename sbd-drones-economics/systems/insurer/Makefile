.PHONY: help unit-test integration-test tests docker-up docker-down docker-logs wait-kafka

CORE_SERVICES = zookeeper kafka kafdrop insurance-service
TEST_SERVICE = tests
INSURANCE_REPLICAS ?= 1
INSURANCE_INSTANCE_ID ?=
TEST_INSTANCE_ID ?= 1

help:
	@echo "make docker-up         - Запустить систему (по умолчанию 1 реплика insurance-service)"
	@echo "                         Пример: make docker-up INSURANCE_REPLICAS=3"
	@echo "                         Опционально: make docker-up INSURANCE_INSTANCE_ID=1"
	@echo "make docker-down       - Остановить систему"
	@echo "make docker-logs       - Логи"
	@echo "make unit-test         - Unit тесты компонентов"
	@echo "make integration-test  - Интеграционные тесты (docker required)"
	@echo "make wait-kafka        - Дождаться готовности Kafka"
	@echo "make tests             - Все тесты"

docker-up:
	@INSURANCE_INSTANCE_ID=$(INSURANCE_INSTANCE_ID) docker compose up -d --build --scale insurance-service=$(INSURANCE_REPLICAS) $(CORE_SERVICES)

docker-down:
	@docker compose down 2>/dev/null

docker-logs:
	@docker compose logs -f

unit-test:
	@mvn test

wait-kafka:
	@for i in $$(seq 1 120); do \
		docker compose exec -T kafka sh -lc '/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --list >/dev/null 2>&1' && \
		echo "Kafka is ready" && exit 0; \
		echo "Waiting for Kafka metadata... ($$i/120)"; \
		sleep 2; \
	done; \
	echo "Kafka is not ready in time"; \
	exit 1

integration-test:
	@$(MAKE) docker-up INSURANCE_REPLICAS=1 INSURANCE_INSTANCE_ID=$(TEST_INSTANCE_ID)
	@$(MAKE) wait-kafka
	@INSURER_INSTANCE_ID=$(TEST_INSTANCE_ID) docker compose run --build --rm --entrypoint go $(TEST_SERVICE) test -race -v ./...
	-$(MAKE) docker-down

tests: unit-test integration-test
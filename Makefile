ENV ?= local

.PHONY: up down restart logs check ps rebuild bootstrap refresh-ip

refresh-ip:
	@./scripts/refresh-ip.sh $(ENV)

up:
	@./start.sh $(ENV) up -d --build
	@sleep 8
	@./scripts/check.sh $(ENV)

down:
	@./start.sh $(ENV) down

restart:
	@./start.sh $(ENV) down
	@./start.sh $(ENV) up -d --build
	@sleep 8
	@./scripts/check.sh $(ENV)

logs:
	@./start.sh $(ENV) logs -f bridge

logs-platform:
	@./start.sh $(ENV) logs -f platform

check:
	@./scripts/check.sh $(ENV)

bootstrap:
	@./start.sh $(ENV) run --rm platform_init

ps:
	@./start.sh $(ENV) ps

rebuild:
	@./start.sh $(ENV) up -d --build

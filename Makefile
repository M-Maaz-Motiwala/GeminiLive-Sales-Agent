.PHONY: up down restart logs check ps rebuild bootstrap refresh-ip

refresh-ip:
	@./scripts/refresh-ip.sh

up:
	@./start.sh up -d --build
	@sleep 8
	@./scripts/check.sh

down:
	@./start.sh down

restart:
	@./start.sh down
	@./start.sh up -d --build
	@sleep 8
	@./scripts/check.sh

logs:
	docker logs -f gemini_bridge

logs-platform:
	docker logs -f aura_platform

check:
	@./scripts/check.sh

bootstrap:
	@./start.sh run --rm platform_init

ps:
	@docker ps --filter name=aura_ --filter name=gemini_bridge --filter name=asterisk

rebuild:
	@./start.sh up -d --build

.PHONY: up down restart logs check ps rebuild

up:
	@./start.sh up -d --build
	@sleep 3
	@./scripts/check.sh

down:
	@./start.sh down

restart:
	@./start.sh down
	@./start.sh up -d --build
	@sleep 3
	@./scripts/check.sh

logs:
	docker logs -f gemini_bridge

check:
	@./scripts/check.sh

ps:
	@docker ps --filter name=gemini_bridge --filter name=asterisk

rebuild:
	@./start.sh up -d --build

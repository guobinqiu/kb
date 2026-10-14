_chat-deploy: _network-up
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml up -d --build --force-recreate

_chat-build:
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml build

_chat-start:
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml start

_chat-stop:
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml stop

_chat-remove:
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml down

_chat-restart:
	docker compose --env-file deploy/.env -p kb_chat -f deploy/chat.yaml restart

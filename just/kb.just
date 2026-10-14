_kb-deploy: _network-up
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml up -d --build --force-recreate

_kb-build:
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml build

_kb-start:
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml start

_kb-stop:
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml stop

_kb-remove:
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml down

_kb-restart:
	docker compose --env-file deploy/.env -p kb_api -f deploy/kb.yaml restart

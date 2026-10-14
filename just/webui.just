_webui-deploy: _network-up
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml up -d --build --force-recreate

_webui-build:
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml build

_webui-start:
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml start

_webui-stop:
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml stop

_webui-remove:
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml down

_webui-restart:
	docker compose --env-file deploy/.env -p kb_webui -f deploy/webui.yaml restart

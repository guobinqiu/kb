_tei-deploy: _network-up
	docker compose --env-file deploy/.env -p kb_tei -f deploy/tei.yaml up -d

_tei-start:
	docker compose --env-file deploy/.env -p kb_tei -f deploy/tei.yaml start

_tei-stop:
	docker compose --env-file deploy/.env -p kb_tei -f deploy/tei.yaml stop

_tei-remove:
	docker compose --env-file deploy/.env -p kb_tei -f deploy/tei.yaml down

_tei-restart:
	docker compose --env-file deploy/.env -p kb_tei -f deploy/tei.yaml restart

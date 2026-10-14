_mineru-deploy: _network-up
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml up -d

_mineru-start:
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml start

_mineru-stop:
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml stop

_mineru-remove:
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml down

_mineru-restart:
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml restart

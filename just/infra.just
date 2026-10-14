_infra-deploy: _network-up
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml up -d

_infra-start:
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml start

_infra-stop:
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml stop

_infra-remove:
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml down

_infra-restart:
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml restart

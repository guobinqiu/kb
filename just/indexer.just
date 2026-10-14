_indexer-deploy: _network-up
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml up -d --build --force-recreate

_indexer-build:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml build

_indexer-start:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml start

_indexer-stop:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml stop

_indexer-remove:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml down

_indexer-restart:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml restart

set dotenv-load := true
set dotenv-path := "deploy/.env"

infra action:
	just _infra-{{action}}

kb action:
	just _kb-{{action}}

indexer action:
	just _indexer-{{action}}

chat action:
	just _chat-{{action}}

webui action:
	just _webui-{{action}}

tei action:
	just _tei-{{action}}

mineru action:
	just _mineru-{{action}}

_infra-up: _network-up
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml up -d

_infra-down:
	docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml down

_kb-up: _network-up
	docker compose --env-file deploy/.env -p kb-api -f deploy/kb.yaml up -d --build --force-recreate

_kb-down:
	docker compose --env-file deploy/.env -p kb-api -f deploy/kb.yaml down

_kb-build:
	docker compose --env-file deploy/.env -p kb-api -f deploy/kb.yaml build

_indexer-up: _network-up
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml up -d --build --force-recreate

_indexer-down:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml down

_indexer-build:
	docker compose --env-file deploy/.env -p kb-indexer -f deploy/indexer.yaml build

_chat-up: _network-up
	docker compose --env-file deploy/.env -p kb-chat -f deploy/chat.yaml up -d --build --force-recreate

_chat-down:
	docker compose --env-file deploy/.env -p kb-chat -f deploy/chat.yaml down

_chat-build:
	docker compose --env-file deploy/.env -p kb-chat -f deploy/chat.yaml build

_webui-up: _network-up _webui-build
	docker compose --env-file deploy/.env -p kb-webui -f deploy/webui.yaml up -d --force-recreate

_webui-down:
	docker compose --env-file deploy/.env -p kb-webui -f deploy/webui.yaml down

_webui-build:
	npm --prefix webui run build

_tei-up: _network-up
	docker compose --env-file deploy/.env -p kb-tei -f deploy/tei.yaml up -d

_tei-down:
	docker compose --env-file deploy/.env -p kb-tei -f deploy/tei.yaml down

_mineru-up: _network-up
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml up -d

_mineru-down:
	docker compose --env-file deploy/.env -p kb-mineru -f deploy/mineru.yaml down

_network-up:
	docker network inspect kb-net >/dev/null 2>&1 || docker network create kb-net

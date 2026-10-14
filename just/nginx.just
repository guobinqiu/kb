_nginx-deploy: _network-up
	docker compose --env-file deploy/.env -p kb-nginx -f deploy/nginx.yaml up -d

_nginx-start:
	docker compose --env-file deploy/.env -p kb-nginx -f deploy/nginx.yaml start

_nginx-stop:
	docker compose --env-file deploy/.env -p kb-nginx -f deploy/nginx.yaml stop

_nginx-remove:
	docker compose --env-file deploy/.env -p kb-nginx -f deploy/nginx.yaml down

_nginx-restart:
	docker compose --env-file deploy/.env -p kb-nginx -f deploy/nginx.yaml restart

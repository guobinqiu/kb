set dotenv-load
set dotenv-path := "deploy/.env"

import 'just/network.just'
import 'just/infra.just'
import 'just/kb.just'
import 'just/indexer.just'
import 'just/chat.just'
import 'just/webui.just'
import 'just/nginx.just'
import 'just/tei.just'
import 'just/mineru.just'

deploy service:
    @just _{{ service }}-deploy

build service:
    @just _{{ service }}-build

start service:
    @just _{{ service }}-start

stop service:
    @just _{{ service }}-stop

remove service:
    @just _{{ service }}-remove

restart service:
    @just _{{ service }}-restart

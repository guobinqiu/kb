import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const expected = {
  'infra.yaml': ['kb_otel_collector', 'kb_jaeger', 'kb_postgres', 'kb_rabbitmq', 'kb_qdrant', 'kb_minio', 'kb_etcd', 'kb_milvus'],
  'kb.yaml': ['kb_api'],
  'indexer.yaml': ['kb_indexer'],
  'chat.yaml': ['kb_chat'],
  'webui.yaml': ['kb_webui'],
  'tei.yaml': ['kb_tei_dense', 'kb_tei_rerank'],
  'mineru.yaml': ['kb_mineru_vlm_server', 'kb_mineru_api_server'],
  'nginx.yaml': ['kb_nginx'],
}

test('all KB Compose containers use a kb_ name', async () => {
  for (const [file, names] of Object.entries(expected)) {
    const config = await readFile(new URL(`../../deploy/${file}`, import.meta.url), 'utf8')
    const actual = [...config.matchAll(/^    container_name: (\S+)$/gm)].map(match => match[1])
    assert.deepEqual(actual, names, file)
  }
})

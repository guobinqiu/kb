import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const deployFile = async path => readFile(new URL(`../../deploy/${path}`, import.meta.url), 'utf8')

test('Nginx routes three configured hosts to existing KB services', async () => {
  const config = await deployFile('nginx/default.conf.template')
  assert.match(config, /server_name \$\{KB_WEB_DOMAIN\};[\s\S]*proxy_pass http:\/\/webui:80;/)
  assert.match(config, /server_name \$\{KB_API_DOMAIN\};[\s\S]*proxy_pass http:\/\/kb_api:6100;/)
  assert.match(config, /server_name \$\{KB_CHAT_DOMAIN\};[\s\S]*proxy_pass http:\/\/chat:6001;/)
})

test('domain entry has its own Compose project and commands', async () => {
  const compose = await deployFile('nginx.yaml')
  const env = await deployFile('env.example')
  const just = await readFile(new URL('../../justfile', import.meta.url), 'utf8')
  assert.match(compose, /KB_HTTP_PORT:-80/)
  assert.match(compose, /kb-net/)
  for (const name of ['KB_WEB_DOMAIN', 'KB_API_DOMAIN', 'KB_CHAT_DOMAIN']) {
    assert.match(compose, new RegExp(name))
    assert.match(env, new RegExp(`^${name}=`, 'm'))
  }
  assert.match(just, /nginx action:/)
  assert.match(just, /_nginx-up:/)
  assert.match(just, /_nginx-down:/)
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const { normalizeFrontendMcpConfiguration: normalize } = await import(pathToFileURL(
  resolve(process.env.QWEN_B83_SOURCE, 'server/src/frontend/tools/mcp/frontend-mcp-config.mjs'),
))
const enabled = { QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP: 'true', HA_MCP_AUTHORIZATION: 'Bearer test-only-token' }
function config(url = 'http://192.168.3.94:8123/api/mcp/assist', headers = { authorization: '${HA_MCP_AUTHORIZATION}' }) {
  return { version: 1, servers: { homeassistant: {
    enabled: true, transport: { type: 'streamable-http', url, headers },
    tools: { fixture_read: { enabled: true } },
  } } }
}
function transport(url, env = enabled, headers) {
  return normalize(config(url, headers), { env }).servers[0].transport
}

test('RFC1918 HTTP Bearer access requires explicit exact true opt-in', () => {
  for (const value of [undefined, 'false', '1', 'TRUE', true]) {
    assert.throws(() => transport(undefined, { ...enabled, QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP: value }))
  }
  for (const host of ['10.0.0.0', '10.255.255.255', '172.16.0.0', '172.31.255.255', '192.168.0.0', '192.168.255.255']) {
    const url = `http://${host}:8123/api/mcp/assist`
    assert.deepEqual(transport(url), {
      type: 'streamable-http', url, headers: { authorization: 'Bearer test-only-token' },
    })
  }
})

test('opt-in never admits public, link-local, CGNAT, DNS or IPv6 HTTP', () => {
  for (const host of ['8.8.8.8', '172.15.255.255', '172.32.0.0', '192.169.0.1', '169.254.169.254', '100.64.0.1', '0.0.0.0', 'ha.example.test', '192.168.1.1.example.test', '[::ffff:192.168.1.1]', '[fd00::1]']) {
    for (const headers of [{}, { authorization: '${HA_MCP_AUTHORIZATION}' }]) {
      assert.throws(() => transport(`http://${host}/api/mcp/assist`, enabled, headers))
    }
  }
})

test('private exception requires valid Bearer credentials and exact env expansion', () => {
  for (const authorization of ['', 'Basic abc', 'Bearer', 'Bearer two tokens', 'Bearer ${HA_MCP_AUTHORIZATION}', 'Bearer token\r\nx-injected: yes']) {
    assert.throws(() => transport(undefined, enabled, { authorization }))
  }
  assert.throws(() => transport(undefined, enabled, {}))
  assert.throws(() => transport(undefined, { QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP: 'true' }), /environment variable is missing/)
  assert.equal(transport(undefined).headers.authorization, 'Bearer test-only-token')
})

test('URL credentials, fragment, malformed URL and unsupported protocols remain rejected', () => {
  for (const url of ['invalid', 'http://192.168.1.1:bad/mcp', 'http://user:pass@192.168.1.1/mcp', 'http://192.168.1.1/mcp#x', 'ftp://192.168.1.1/mcp', 'file:///tmp/mcp']) {
    assert.throws(() => transport(url))
  }
})

test('remote HTTPS and original header-free loopback behavior are preserved', () => {
  assert.equal(transport('https://ha.example.test/api/mcp/assist', { HA_MCP_AUTHORIZATION: 'Bearer test-only-token' }).url, 'https://ha.example.test/api/mcp/assist')
  for (const host of ['localhost', '127.0.0.1']) {
    assert.equal(transport(`http://${host}/mcp`, {}, {}).url, `http://${host}/mcp`)
    assert.throws(() => transport(`http://${host}/mcp`))
  }
})

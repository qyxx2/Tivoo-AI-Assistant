import assert from 'node:assert/strict'
import test from 'node:test'
import { enabledToolNames, waitForHaMcp } from '../wait-ha-mcp.mjs'

test('enabledToolNames reads only enabled tools from the named server', () => {
  assert.deepEqual(enabledToolNames({ servers: { homeassistant: { tools: {
    b: { enabled: false }, a: { enabled: true }, c: { enabled: true },
  } } } }), ['a', 'c'])
})

test('waitForHaMcp waits through endpoint and partial-catalog startup states', async () => {
  const replies = [
    { ok: false, status: 404 },
    { ok: true, status: 200, json: async () => ({ result: { tools: [{ name: 'a' }] } }) },
    { ok: true, status: 200, json: async () => ({ result: { tools: [{ name: 'a' }, { name: 'b' }] } }) },
  ]
  let calls = 0
  const result = await waitForHaMcp({
    url: 'http://192.168.3.94:8123/api/mcp/assist',
    authorization: 'Bearer test-only',
    required: ['a', 'b'],
    timeoutMs: 1_000,
    intervalMs: 0,
    fetchImpl: async () => replies[calls++],
    sleep: async () => {},
    log: () => {},
  })
  assert.equal(calls, 3)
  assert.equal(result.ready, true)
  assert.equal(result.remoteCount, 2)
})

test('waitForHaMcp fails closed when required tools never appear', async () => {
  await assert.rejects(
    waitForHaMcp({
      url: 'http://192.168.3.94:8123/api/mcp/assist',
      authorization: 'Bearer test-only',
      required: ['required'],
      timeoutMs: 1,
      intervalMs: 0,
      fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ result: { tools: [] } }) }),
      sleep: async () => {},
      log: () => {},
    }),
    /startup wait timed out/,
  )
})

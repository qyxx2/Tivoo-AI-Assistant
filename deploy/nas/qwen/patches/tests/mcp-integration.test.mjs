import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { networkInterfaces } from 'node:os'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'

const source = name => import(pathToFileURL(resolve(process.env.QWEN_B83_SOURCE, `server/src/${name}.mjs`)))
const { normalizeFrontendMcpConfiguration } = await source('frontend/tools/mcp/frontend-mcp-config')
const { FrontendMcpClient } = await source('frontend/tools/mcp/frontend-mcp-client')
const { ToolCallHandler } = await source('frontend/tools/tool-call-handler')
const { RealtimeTurnState } = await source('voice/realtime-turn-state')
const { RealtimePresentationRuntime } = await source('voice/realtime-presentation-runtime')
const { AnnouncementWindow } = await source('voice/announcement/announcement-window')

// Bind a local interface, never connect to NAS/HA. A private IPv4 interface is
// needed to exercise the real patched URL policy and unmodified SDK transport.
const bindAddress = Object.values(networkInterfaces()).flat().find(item =>
  item.family === 'IPv4' && /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/u.test(item.address),
)?.address
assert.ok(bindAddress, 'MCP integration tests require a local RFC1918 IPv4 interface')

async function fixture(t, { mode = 'ok', timeoutMs = 1000, token = 'Bearer b83-fixture-only', missingTool = false } = {}) {
  const requests = []
  const pendingTimers = new Set()
  const server = createServer(async (req, res) => {
    if (req.headers.authorization !== 'Bearer b83-fixture-only') {
      res.writeHead(401).end()
      return
    }
    if (req.method !== 'POST') { res.writeHead(405).end(); return }
    let raw = ''
    for await (const chunk of req) raw += chunk
    const body = JSON.parse(raw)
    requests.push({ ...body, authorization: req.headers.authorization, path: req.url })
    if (!('id' in body)) { res.writeHead(202).end(); return }
    const reply = (result, error) => {
      if (res.destroyed) return
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({
        jsonrpc: '2.0', id: body.id, ...(error ? { error } : { result }),
      }))
    }
    if (body.method === 'initialize') {
      reply({ protocolVersion: body.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'b83-fixture', version: '1' } })
    } else if (body.method === 'tools/list') {
      const names = missingTool ? ['not_allowlisted'] : ['fixture_read', 'not_allowlisted']
      reply({ tools: names.map(name => ({ name, description: 'Local fixture only', inputSchema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] } })) })
    } else if (body.method === 'tools/call') {
      if (mode === 'rpc-error') { reply(null, { code: -32603, message: 'fixture transport failure' }); return }
      const result = mode === 'tool-error'
        ? { isError: true, content: [{ type: 'text', text: 'fixture service rejected request' }] }
        : { content: [{ type: 'text', text: mode === 'large' ? '语'.repeat(10000) : `fixture result: ${body.params.arguments.query}` }] }
      if (mode === 'slow') {
        const timer = setTimeout(() => { pendingTimers.delete(timer); reply(result) }, 350)
        pendingTimers.add(timer)
      } else reply(result)
    } else reply({})
  })
  await new Promise(resolve => server.listen(0, bindAddress, resolve))
  const url = `http://${bindAddress}:${server.address().port}/api/mcp/assist`
  const configuration = normalizeFrontendMcpConfiguration({ version: 1, servers: { homeassistant: {
    enabled: true, connectTimeoutMs: 2000,
    transport: { type: 'streamable-http', url: '${HA_ASSIST_MCP_URL}', headers: { authorization: '${HA_MCP_AUTHORIZATION}' } },
    tools: { fixture_read: { enabled: true, timeoutMs, maxResultBytes: 1024, maxCallsPerTurn: 2 }, not_allowlisted: { enabled: false } },
  } } }, { env: { QWEN_AUDIO_FRONTEND_MCP_ALLOW_PRIVATE_HTTP: 'true', HA_ASSIST_MCP_URL: url, HA_MCP_AUTHORIZATION: token } })
  const client = new FrontendMcpClient({ configuration })
  t.after(async () => {
    await client.close()
    for (const timer of pendingTimers) clearTimeout(timer)
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  })
  await client.initialize()
  return { client, requests }
}
const name = 'mcp__homeassistant__fixture_read'

test('real Streamable HTTP initializes, expands env headers, filters tools and calls exact remote name', async t => {
  const { client, requests } = await fixture(t)
  assert.equal(client.health().ok, true)
  assert.deepEqual(client.tools().map(tool => tool.name), [name])
  assert.equal((await client.execute(name, { query: 'living room' })).text, 'fixture result: living room')
  assert.deepEqual(requests.slice(0, 3).map(r => r.method), ['initialize', 'notifications/initialized', 'tools/list'])
  const call = requests.find(r => r.method === 'tools/call')
  assert.deepEqual(call.params, { name: 'fixture_read', arguments: { query: 'living room' } })
  assert.ok(requests.every(r => r.authorization === 'Bearer b83-fixture-only' && r.path === '/api/mcp/assist'))
  await assert.rejects(client.execute('mcp__homeassistant__not_allowlisted', {}), /not enabled/)
  assert.equal(requests.filter(r => r.method === 'tools/call').length, 1)
})

test('result UTF8 size is bounded and remote tool errors remain errors', async t => {
  const large = await fixture(t, { mode: 'large' })
  const result = await large.client.execute(name, { query: 'x' })
  assert.ok(Buffer.byteLength(JSON.stringify(result)) <= 1024)
  assert.ok(result.text.length > 0 && result.text.length < 10000)
  const failure = await fixture(t, { mode: 'tool-error' })
  const output = await failure.client.execute(name, { query: 'x' })
  assert.equal(output.error, true)
  assert.equal(output.error_code, 'frontend_mcp_tool_failed')
})

test('timeouts, interruption and JSON-RPC failures propagate', async t => {
  const slow = await fixture(t, { mode: 'slow', timeoutMs: 100 })
  await assert.rejects(slow.client.execute(name, { query: 'x' }), { code: 'frontend_mcp_tool_aborted' })
  const controller = new AbortController()
  const interrupted = slow.client.execute(name, { query: 'x' }, { signal: controller.signal })
  controller.abort()
  await assert.rejects(interrupted, { code: 'frontend_mcp_tool_aborted' })
  const broken = await fixture(t, { mode: 'rpc-error' })
  await assert.rejects(broken.client.execute(name, { query: 'x' }), /fixture transport failure/)
})

test('unauthorized and missing allowlisted tools fail discovery closed', async t => {
  for (const options of [{ token: 'Bearer invalid-fixture-only' }, { missingTool: true }]) {
    const { client } = await fixture(t, options)
    assert.equal(client.health().ok, false)
    assert.deepEqual(client.tools(), [])
    await assert.rejects(client.execute(name, { query: 'x' }), /not enabled/)
  }
})

test('MCP result continues the same Agent turn across intermediate response and audio completion', async t => {
  const { client } = await fixture(t, { mode: 'slow' })
  const turns = new RealtimeTurnState()
  const context = turns.beginManual('b83-turn').context
  const window = new AnnouncementWindow()
  window.beginTurn(context.turnId)
  window.endSpeech()
  const outputs = [], continuations = [], events = []
  const frontend = {
    ready: true, provider: { outputSampleRate: 24000 }, capabilities: {},
    sendFunctionOutput: async (...args) => outputs.push(args),
    ensureResponse: async (...args) => continuations.push(args),
  }
  const handler = new ToolCallHandler({
    ownerId: 'b83-owner', sessionId: 'b83-session',
    getFrontend: () => frontend, getTurnId: () => context.turnId,
    getTurnGeneration: () => context.turnGeneration, frontendToolSources: [client],
  })
  const runtime = new RealtimePresentationRuntime({
    ownerId: 'b83-owner', sessionId: 'b83-session', turns,
    conversationSync: { record() {} }, announcementWindow: window,
    announcements: { flush() {}, confirmMany() {}, retryMany() {} }, toolCalls: handler,
    send: event => events.push(event), getFrontend: () => frontend,
    getOutputEnabled: () => true, getNonVoiceClient: () => false,
    getResponseTurnCandidate: () => context, clearResponseCandidate() {},
    announcementQuietMs: 0, responseContextCleanupMs: 0,
  })
  const deliver = event => { runtime.begin(event); runtime.handle(event) }
  deliver({ type: 'response.created', response: { id: 'tool-response' }, __voiceContext: context })
  runtime.markFunctionCall('tool-response')
  const pending = handler.handle({ call_id: 'b83-call', name, arguments: '{"query":"guitar"}' }, { ...context, responseId: 'tool-response' })
  deliver({ type: 'response.audio.done', response_id: 'tool-response' })
  deliver({ type: 'response.done', response: { id: 'tool-response', status: 'completed' } })
  assert.equal(window.isBlocked(), true)
  assert.equal(continuations.length, 0)
  await pending
  assert.equal(outputs.length, 1)
  assert.equal(outputs[0][0], 'b83-call')
  assert.equal(outputs[0][1].text, 'fixture result: guitar')
  assert.equal(outputs[0][2].turnId, 'b83-turn')
  assert.equal(outputs[0][3].createResponse, false)
  assert.equal(continuations.length, 1)
  assert.equal(continuations[0][0].turnId, 'b83-turn')
  assert.equal(continuations[0][0].turnGeneration, context.turnGeneration)
  assert.equal(continuations[0][1].afterToolResults, true)
  assert.equal(window.isBlocked(), true)
  deliver({ type: 'response.created', response: { id: 'final-response' }, __voiceContext: context })
  deliver({ type: 'response.audio_transcript.done', response_id: 'final-response', transcript: 'fixture complete.' })
  deliver({ type: 'response.done', response: { id: 'final-response', status: 'completed' } })
  assert.equal(window.isBlocked(), false)
  assert.deepEqual(turns.current(), context)
})

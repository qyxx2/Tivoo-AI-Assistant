import assert from 'node:assert/strict'
import test from 'node:test'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const root = process.env.QWEN_B85_SOURCE
assert.ok(root, 'Set QWEN_B85_SOURCE to the temporary locked source archive')
const load = path => import(pathToFileURL(resolve(root, path)))
const { RealtimePresentationRuntime } = await load('server/src/voice/realtime-presentation-runtime.mjs')
const { RealtimeTurnState } = await load('server/src/voice/realtime-turn-state.mjs')
const { GatewayClientProtocolSession } = await load('server/src/transport/gateway-client-protocol-session.mjs')
const { parseGatewayServerMessage } = await load('shared/protocol/gateway-events.mjs')
const { parseGatewayServerProtocolMessage } = await load('shared/protocol/gateway-client-protocol.mjs')

const capability = 'response.terminal-status'
function session(request = true, options = {}) {
  const protocol = new GatewayClientProtocolSession({ sessionId: 'fixture', ...options })
  const ready = protocol.receive({
    type: 'session.hello', event_id: 'hello', protocol: { min: '7.0.0', max: '7.0.0' },
    client: { type: 'fixture', instance_id: 'fixture' }, capabilities: request ? [capability] : [],
  }).reply
  return { protocol, ready }
}
function harness({ playbackReceipts = false, tool = false, summary = tool } = {}) {
  const events = []
  const turns = new RealtimeTurnState()
  turns.beginManual('fixture-turn')
  const runtime = new RealtimePresentationRuntime({
    ownerId: 'fixture', sessionId: 'fixture', turns,
    conversationSync: { record() {} },
    announcementWindow: { queueAudio() {}, startPlayback() {}, finishPlayback() {}, responseDone() {} },
    announcements: { confirmMany() {}, retryMany() {}, flush() {} },
    toolCalls: { requiresToolResultSummary: () => summary, consumeTerminalToolResponse: () => false, finishToolResponse: async () => {} },
    send: e => events.push(e),
    getFrontend: () => ({ ready: true, provider: { outputSampleRate: 24000 }, capabilities: {} }),
    getOutputEnabled: () => true, getNonVoiceClient: () => false,
    getPlaybackReceipts: () => playbackReceipts, getResponseTurnCandidate: () => null,
    clearResponseCandidate() {}, announcementQuietMs: 60000, responseContextCleanupMs: 60000,
  })
  const deliver = e => { runtime.begin(e); runtime.handle(e) }
  deliver({ type: 'response.created', response: { id: 'r' } })
  deliver({ type: 'response.audio.delta', response_id: 'r', delta: 'AAA=' })
  if (playbackReceipts) runtime.startPlayback('r')
  if (tool) runtime.markFunctionCall('r')
  return { runtime, deliver, events }
}

test('terminal-status capability is positively negotiated, never inferred from a version', () => {
  assert.deepEqual(session().ready.capabilities, [capability])
  assert.deepEqual(session(false).ready.capabilities, [])
  assert.deepEqual(session(true, { supportedCapabilities: [] }).ready.capabilities, [])
})

for (const playbackReceipts of [false, true]) {
  for (const status of ['completed', 'cancelled', 'incomplete', 'failed', undefined, 'unexpected']) {
    test(`final question retains exact terminal status ${status} (playback ${playbackReceipts})`, () => {
      const h = harness({ playbackReceipts })
      try {
        h.deliver({ type: 'response.audio_transcript.done', response_id: 'r', transcript: '还需要帮助吗？' })
        h.deliver({ type: 'response.done', response: { id: 'r', status } })
        const done = h.events.find(e => e.type === 'audio.done')
        assert.equal(done.responseStatus, ['completed', 'cancelled', 'incomplete', 'failed'].includes(status) ? status : 'unknown')
        assert.equal(done.awaitsToolFollowUp, false)
        assert.equal(done.hasFunctionCall, false)
        assert.ok(h.events.some(e => e.type === 'transcript.final' && e.content === '还需要帮助吗？'))
        assert.equal(done.turnId, 'fixture-turn')
        const { protocol } = session()
        const wire = JSON.parse(JSON.stringify(protocol.encode(parseGatewayServerMessage(done))))
        for (const field of ['responseStatus', 'awaitsToolFollowUp', 'hasFunctionCall']) assert.equal(parseGatewayServerProtocolMessage(wire)[field], done[field])
      } finally { h.runtime.clear() }
    })
  }
}
for (const summary of [false, true]) {
  test(`tool-bearing question cannot look final even with summary=${summary}`, () => {
    const h = harness({ tool: true, summary })
    try {
      h.deliver({ type: 'response.audio_transcript.done', response_id: 'r', transcript: '还需要帮助吗？' })
      h.deliver({ type: 'response.done', response: { id: 'r', status: 'completed' } })
      const done = h.events.find(e => e.type === 'audio.done')
      assert.equal(done.hasFunctionCall, true)
      assert.equal(done.awaitsToolFollowUp, summary)
      assert.equal(done.responseStatus, 'completed')
    } finally { h.runtime.clear() }
  })
}
for (const status of ['completed', 'cancelled', 'incomplete']) {
  test(`late transcript cannot alter terminal marker ${status}`, () => {
    const h = harness()
    try {
      h.deliver({ type: 'response.done', response: { id: 'r', status } })
      h.deliver({ type: 'response.audio_transcript.done', response_id: 'r', transcript: '还需要帮助吗？' })
      assert.deepEqual(h.events.filter(e => e.type === 'audio.done').map(e => e.responseStatus), [status])
      assert.equal(h.events.some(e => e.type === 'transcript.final'), status === 'completed')
    } finally { h.runtime.clear() }
  })
}
test('provider failure emits failed, never completed', () => {
  const h = harness({ tool: true })
  try {
    h.runtime.failResponse({ response_id: 'r' })
    const done = h.events.find(e => e.type === 'audio.done')
    assert.equal(done.responseStatus, 'failed')
    assert.equal(done.awaitsToolFollowUp, false)
    assert.equal(done.hasFunctionCall, true)
  } finally { h.runtime.clear() }
})
test('legacy clients accept old payload and receive additive new fields unchanged', () => {
  const old = { type: 'audio.done', responseId: 'r', turnId: 'fixture-turn' }
  assert.deepEqual(parseGatewayServerMessage(old), old)
  const protocol = new GatewayClientProtocolSession()
  protocol.receive({ type: 'connect' })
  const added = { ...old, responseStatus: 'completed', awaitsToolFollowUp: false, hasFunctionCall: false }
  assert.deepEqual(protocol.encode(added), added)
})
test('schema rejects invalid status/continuation markers without stripping valid extensions', () => {
  const base = { type: 'audio.done', responseId: 'r' }
  for (const invalid of [{ responseStatus: 'success' }, { awaitsToolFollowUp: 'false' }, { hasFunctionCall: 0 }]) {
    assert.throws(() => parseGatewayServerMessage({ ...base, ...invalid }))
  }
})

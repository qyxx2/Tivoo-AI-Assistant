// B8.5 pre-implementation diagnostic. No network, credentials or source writes.
// Usage: node terminal_gate.mjs /path/to/locked/qwen-audio-agent
// Exit 2 means the required terminal observability gate remains HOLD.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

assert.ok(process.argv[2], 'Pass the locked Qwen 2.1.0 source directory')
const root = resolve(process.argv[2])
const hashes = {
  'server/src/voice/realtime-presentation-runtime.mjs': '0f71e77fcd14081ae2cf427f2bd60e5a183aa5a49381a9e57460a1dd8b06bea3',
  'server/src/voice/realtime-session-runtime.mjs': 'fe31895043bb1f886054627d29dbcd341e2ecd56eca4f85788fcbc7821c261dd',
  'shared/protocol/realtime-events.mjs': 'f8fa168fa46257953a0070c18cbc67701d780c367cad40511650a05c913a156f',
}
for (const [file, expected] of Object.entries(hashes)) {
  const actual = createHash('sha256').update(await readFile(resolve(root, file))).digest('hex')
  assert.equal(actual, expected, `Re-audit changed upstream file: ${file}`)
}
const source = name => import(pathToFileURL(resolve(root, `server/src/voice/${name}.mjs`)))
const { RealtimePresentationRuntime } = await source('realtime-presentation-runtime')
const { RealtimeTurnState } = await source('realtime-turn-state')
const { AnnouncementWindow } = await source('announcement/announcement-window')

async function observe(status, { playbackReceipts, tool = false }) {
  const events = []
  const turns = new RealtimeTurnState()
  turns.beginManual('mic-turn-fixture')
  const window = new AnnouncementWindow()
  window.beginTurn(turns.turnId)
  window.endSpeech()
  const runtime = new RealtimePresentationRuntime({
    ownerId: 'fixture-owner', sessionId: 'fixture-session', turns,
    conversationSync: { record() {} }, announcementWindow: window,
    announcements: { confirmMany() {}, retryMany() {}, flush() {} },
    toolCalls: {
      requiresToolResultSummary: () => tool,
      consumeTerminalToolResponse: () => false,
      finishToolResponse: async () => {},
    },
    send: event => events.push(event),
    getFrontend: () => ({ ready: true, provider: { outputSampleRate: 24000 } }),
    getOutputEnabled: () => true, getNonVoiceClient: () => false,
    getPlaybackReceipts: () => playbackReceipts,
    getResponseTurnCandidate: () => null, clearResponseCandidate() {},
    announcementQuietMs: 0,
  })
  const deliver = event => { runtime.begin(event); runtime.handle(event) }
  try {
    deliver({ type: 'response.created', response: { id: 'response-fixture' } })
    deliver({ type: 'response.audio.delta', response_id: 'response-fixture', delta: 'AAA=' })
    if (playbackReceipts) runtime.startPlayback('response-fixture')
    deliver({ type: 'response.audio_transcript.done', response_id: 'response-fixture', transcript: '还需要帮助吗？' })
    if (tool) runtime.markFunctionCall('response-fixture')
    deliver({ type: 'response.done', response: { id: 'response-fixture', status } })
    await new Promise(resolve => setTimeout(resolve, 5))
    assert.ok(events.some(e => e.type === 'transcript.final'
      && e.role === 'assistant' && e.content === '还需要帮助吗？'
      && e.turnId === turns.turnId && e.responseId === 'response-fixture'))
    assert.ok(events.some(e => e.type === 'audio.done' && e.responseId === 'response-fixture'))
    return events
  } finally {
    runtime.clear()
  }
}

let hold = false
for (const playbackReceipts of [true, false]) {
  const completed = await observe('completed', { playbackReceipts })
  for (const status of ['cancelled', 'incomplete']) {
    const abnormal = await observe(status, { playbackReceipts })
    const identical = JSON.stringify(completed) === JSON.stringify(abnormal)
    console.log(JSON.stringify({ playbackReceipts, compared: ['completed', status], identical, events: abnormal }))
    hold ||= identical
  }
}
const intermediate = await observe('completed', { playbackReceipts: true, tool: true })
assert.ok(intermediate.some(e => e.type === 'audio.done'))
console.log(JSON.stringify({ toolIntermediateHasFinalQuestionAndAudioDone: true }))
console.log(hold ? 'B8.5 terminal gate: HOLD' : 'B8.5 terminal gate: requires further full-session audit')
// This narrow presentation probe can disprove readiness, never certify it.
process.exitCode = hold ? 2 : 3

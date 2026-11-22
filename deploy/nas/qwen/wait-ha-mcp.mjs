#!/usr/bin/env node
import { readFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'

const DEFAULT_CONFIG = '/root/.config/qwaudio/frontend-mcp.json'
const DEFAULT_TIMEOUT_MS = 120_000
const DEFAULT_INTERVAL_MS = 1_000
const REQUEST_TIMEOUT_MS = 3_000

export function enabledToolNames(config, serverKey = 'homeassistant') {
  const server = config?.servers?.[serverKey]
  if (!server || typeof server !== 'object') {
    throw new Error(`Frontend MCP server is missing: ${serverKey}`)
  }
  return Object.entries(server.tools || {})
    .filter(([, policy]) => policy?.enabled === true)
    .map(([name]) => name)
    .sort()
}

export async function probeHaMcp({ url, authorization, required, fetchImpl = fetch }) {
  const response = await fetchImpl(url, {
    method: 'POST',
    headers: {
      Authorization: authorization,
      'Content-Type': 'application/json',
      Accept: 'application/json, text/event-stream',
    },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  if (!response.ok) return { ready: false, reason: `HTTP ${response.status}` }
  const body = await response.json()
  const remote = new Set((body?.result?.tools || []).map(tool => tool?.name).filter(Boolean))
  const missing = required.filter(name => !remote.has(name))
  return { ready: missing.length === 0, missing, remoteCount: remote.size }
}

export async function waitForHaMcp({
  url,
  authorization,
  required,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  intervalMs = DEFAULT_INTERVAL_MS,
  fetchImpl = fetch,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  log = message => console.error(message),
}) {
  const deadline = Date.now() + timeoutMs
  let last = 'not attempted'
  while (Date.now() < deadline) {
    try {
      const result = await probeHaMcp({ url, authorization, required, fetchImpl })
      if (result.ready) return result
      last = result.reason || `missing ${result.missing.length}/${required.length} tools`
    } catch (error) {
      last = error?.name === 'TimeoutError' ? 'request timeout' : String(error?.message || error)
    }
    log(`HA MCP not ready: ${last}`)
    await sleep(intervalMs)
  }
  throw new Error(`HA MCP startup wait timed out: ${last}`)
}

export async function main(env = process.env) {
  const configPath = env.QWEN_AUDIO_FRONTEND_MCP_CONFIG || DEFAULT_CONFIG
  const url = env.HA_ASSIST_MCP_URL
  const authorization = env.HA_MCP_AUTHORIZATION
  if (!url) throw new Error('HA_ASSIST_MCP_URL is required')
  if (!authorization) throw new Error('HA_MCP_AUTHORIZATION is required')
  const config = JSON.parse(await readFile(configPath, 'utf8'))
  const required = enabledToolNames(config)
  if (required.length === 0) throw new Error('No enabled Home Assistant MCP tools configured')
  const result = await waitForHaMcp({ url, authorization, required })
  console.error(`HA MCP ready: ${result.remoteCount} discovered, ${required.length} required`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    console.error(error.message)
    process.exitCode = 1
  })
}

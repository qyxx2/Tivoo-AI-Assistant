#!/usr/bin/env node
// Temporary P6.8 B8.2 direct GCP 7.0 probe.
// Runs inside the existing Qwen container. Never connects to HA or ESP32;
// audio.delta payloads are counted and discarded, never played.
import { createRequire } from "node:module";
import { setTimeout as sleep } from "node:timers/promises";

const require = createRequire("/usr/local/lib/node_modules/qwen-audio-agent/package.json");
const { WebSocket } = require("ws");
const TOKEN = process.env.QWEN_AUDIO_GATEWAY_ACCESS_TOKEN || "";
const BASE_URL = process.env.P68_B82_GATEWAY_URL || "ws://127.0.0.1:3101/api/realtime";
const SAMPLE_RATE = 16000;
const FRAME_MS = 20;
const FRAME_BYTES = 640;
const GCP_VERSION = "7.0.0";

function fail(message) {
  throw new Error(message);
}

function makeId(prefix) {
  return `${prefix}-${globalThis.crypto.randomUUID().replaceAll("-", "")}`;
}

function delay(ms) {
  return sleep(ms);
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function buildUrl(sessionId) {
  const url = new URL(BASE_URL);
  url.searchParams.set("sessionId", sessionId);
  return url.toString();
}

class GatewayConnection {
  constructor(sessionId, instanceId) {
    this.sessionId = sessionId;
    this.instanceId = instanceId;
    this.probeSocketMarker = globalThis.crypto.randomUUID();
    this.helloEventId = makeId("evt_b82");
    this.ws = null;
    this.queue = [];
    this.waiters = [];
    this.failure = null;
    this.handshake = null;
  }

  _push(event) {
    const waiter = this.waiters.shift();
    if (waiter) {
      clearTimeout(waiter.timer);
      waiter.resolve(event);
    } else {
      this.queue.push(event);
    }
  }

  _fail(error) {
    this.failure = error instanceof Error ? error : new Error(String(error));
    for (const waiter of this.waiters.splice(0)) {
      clearTimeout(waiter.timer);
      waiter.reject(this.failure);
    }
  }

  async nextEvent(timeoutMs = 5000) {
    if (this.queue.length) return this.queue.shift();
    if (this.failure) throw this.failure;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) fail("Gateway WebSocket is not open");
    return new Promise((resolve, reject) => {
      const waiter = {
        resolve,
        reject,
        timer: setTimeout(() => {
          const index = this.waiters.indexOf(waiter);
          if (index >= 0) this.waiters.splice(index, 1);
          reject(new Error(`Gateway event timeout after ${timeoutMs}ms`));
        }, timeoutMs),
      };
      this.waiters.push(waiter);
    });
  }

  async send(event) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) fail("Gateway WebSocket is not open");
    await new Promise((resolve, reject) => {
      this.ws.send(JSON.stringify(event), error => error ? reject(error) : resolve());
    });
  }

  async connect() {
    if (!TOKEN) fail("QWEN_AUDIO_GATEWAY_ACCESS_TOKEN is not available inside Qwen runtime");
    this.ws = new WebSocket(buildUrl(this.sessionId), {
      headers: { Authorization: `Bearer ${TOKEN}` },
      perMessageDeflate: false,
      maxPayload: 4 * 1024 * 1024,
    });
    this.ws.on("message", (data, isBinary) => {
      if (isBinary) return this._push({ type: "probe.binary_frame_ignored" });
      try {
        const event = JSON.parse(data.toString("utf8"));
        if (event && typeof event === "object") this._push(event);
      } catch (error) {
        this._fail(new Error(`Invalid Gateway JSON: ${error.message}`));
      }
    });
    this.ws.on("error", error => this._fail(error));
    this.ws.on("close", (code, reason) => {
      if (!this.failure) this._fail(new Error(`Gateway closed socket code=${code} reason=${reason}`));
    });

    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("WebSocket open timeout")), 10000);
      this.ws.once("open", () => { clearTimeout(timer); resolve(); });
      this.ws.once("error", error => { clearTimeout(timer); reject(error); });
    });

    await this.send({
      type: "session.hello",
      event_id: this.helloEventId,
      protocol: { min: GCP_VERSION, max: GCP_VERSION },
      client: {
        type: "embedded",
        version: "p6.8-b8.2-preflight",
        instance_id: this.instanceId,
        label: "P6.8 B8.2 isolated no-hardware probe",
      },
      capabilities: ["input.audio"],
      locale: "zh-CN",
      time_zone: "Asia/Shanghai",
      connection: {
        voice_enabled: true,
        input_enabled: true,
        output_enabled: true,
        text_only: false,
      },
    });

    let readySession = null;
    let voiceReady = null;
    let ownership = null;
    const readyEventNames = [];
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline && (!readySession || !voiceReady || ownership !== "active")) {
      const event = await this.nextEvent(Math.max(100, deadline - Date.now()));
      readyEventNames.push(event.type);
      if (event.type === "error") fail(`session.hello failed: ${JSON.stringify(event.error || event)}`);
      if (event.type === "session.ready") {
        if (event.request_event_id !== this.helloEventId) fail("session.ready request_event_id mismatch");
        readySession = event;
      } else if (event.type === "voice.ready") {
        voiceReady = event;
      } else if (event.type === "voice.ownership") {
        ownership = event.state;
        if (ownership === "busy") fail("Gateway voice owner is busy; probe stopped without takeover");
      }
    }
    if (!readySession || !voiceReady || ownership !== "active") {
      fail(`Incomplete handshake: session=${!!readySession}, voice=${!!voiceReady}, ownership=${ownership}`);
    }
    if (readySession.session_id !== this.sessionId) {
      fail(`Gateway session mismatch: expected ${this.sessionId}, got ${readySession.session_id}`);
    }
    if (voiceReady.inputSampleRate !== SAMPLE_RATE) {
      fail(`Gateway input sample rate ${voiceReady.inputSampleRate}, expected ${SAMPLE_RATE}`);
    }
    this.handshake = {
      gcp_version: readySession.protocol_version,
      session_id: readySession.session_id,
      instance_id: this.instanceId,
      probe_socket_marker: this.probeSocketMarker,
      lease_generation: readySession.connection?.lease_generation ?? null,
      ownership,
      input_sample_rate: voiceReady.inputSampleRate,
      ready_events: readyEventNames,
    };
    return this.handshake;
  }

  async runTurn(turn) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) fail("Same active WebSocket is required for this turn");
    const pcm = Buffer.from(turn.pcm_base64, "base64");
    if (!pcm.length || pcm.length % 2) fail("Input must be non-empty PCM16");
    const tailMs = turn.tail_ms ?? 240;
    if (tailMs < 0 || tailMs % FRAME_MS) fail("tail_ms must be a multiple of 20 ms");
    const frames = [];
    for (let offset = 0; offset < pcm.length; offset += FRAME_BYTES) {
      const frame = Buffer.alloc(FRAME_BYTES);
      pcm.copy(frame, 0, offset, Math.min(offset + FRAME_BYTES, pcm.length));
      frames.push(frame);
    }
    for (let offset = 0; offset < tailMs; offset += FRAME_MS) frames.push(Buffer.alloc(FRAME_BYTES));

    const startedAt = Date.now();
    let sendFinishedAt = null;
    let speechFramesSentAt = null;
    let endpointAt = null;
    let responseStartedAt = null;
    let firstAudioAt = null;
    let senderDone = false;
    let aborted = false;
    let sentBytes = 0;
    const eventCounts = {};
    const transcripts = [];
    const toolCalls = [];
    const toolResponseIds = new Set();
    const doneResponseIds = new Set();
    const audioBytes = {};
    const sampleRates = {};
    const turnIds = new Set();
    const responseIds = new Set();

    const sender = (async () => {
      for (let index = 0; index < frames.length; index += 1) {
        if (aborted) fail("Turn sender aborted");
        await this.send({
          type: "input_audio_buffer.append",
          event_id: makeId("evt_b82"),
          audio: frames[index].toString("base64"),
        });
        sentBytes += frames[index].length;
        if (index === Math.ceil(pcm.length / FRAME_BYTES) - 1) speechFramesSentAt = Date.now();
        await delay(FRAME_MS);
      }
      sendFinishedAt = Date.now();
      senderDone = true;
    })();

    const deadline = Date.now() + frames.length * FRAME_MS + 20000;
    try {
      while (Date.now() < deadline) {
        let event;
        try {
          event = await this.nextEvent(Math.min(5000, Math.max(100, deadline - Date.now())));
        } catch (error) {
          if (error.message.startsWith("Gateway event timeout")) continue;
          throw error;
        }
        const type = event.type || "unknown";
        eventCounts[type] = (eventCounts[type] || 0) + 1;
        const now = Date.now();

        if (type === "error") fail(`Gateway error: ${JSON.stringify(event.error || event)}`);
        if (type === "turn.started" && event.turnId) turnIds.add(event.turnId);
        if (type === "voice.state" && event.state === "processing") endpointAt ??= now;
        if (type === "response.started") {
          responseStartedAt ??= now;
          if (event.responseId) responseIds.add(event.responseId);
          if (event.turnId) turnIds.add(event.turnId);
        }
        if (type === "transcript.final") {
          transcripts.push({
            role: event.role ?? null,
            content: event.content ?? "",
            responseId: event.responseId ?? null,
            turnId: event.turnId ?? null,
          });
          if (event.responseId) responseIds.add(event.responseId);
          if (event.turnId) turnIds.add(event.turnId);
        }
        if (type === "tool.call") {
          toolCalls.push({
            status: event.status ?? null,
            name: event.name ?? null,
            responseId: event.responseId ?? null,
            callId: event.callId ?? null,
          });
          if (event.status === "received" && event.responseId) toolResponseIds.add(event.responseId);
        }
        if (type === "audio.delta") {
          const id = event.responseId || "unknown";
          firstAudioAt ??= now;
          const data = typeof event.audio === "string" ? Buffer.from(event.audio, "base64") : Buffer.alloc(0);
          audioBytes[id] = (audioBytes[id] || 0) + data.length;
          if (Number.isInteger(event.sampleRate)) {
            if (sampleRates[id] !== undefined && sampleRates[id] !== event.sampleRate) {
              fail(`Output sample rate changed within response ${id}`);
            }
            sampleRates[id] = event.sampleRate;
          }
        }
        if (type === "audio.done" && event.responseId) doneResponseIds.add(event.responseId);

        const assistantFinals = transcripts.filter(item =>
          item.role === "assistant" &&
          item.responseId &&
          !toolResponseIds.has(item.responseId) &&
          doneResponseIds.has(item.responseId)
        );
        if (senderDone && assistantFinals.length) break;
      }
      if (!senderDone) fail("Audio sender did not finish");
      await sender;
    } catch (error) {
      aborted = true;
      await sender.catch(() => {});
      throw error;
    }

    const assistantFinals = transcripts.filter(item =>
      item.role === "assistant" &&
      item.responseId &&
      !toolResponseIds.has(item.responseId) &&
      doneResponseIds.has(item.responseId)
    );
    const userFinals = transcripts.filter(item => item.role === "user");
    if (!userFinals.some(item => typeof item.content === "string" && item.content.trim())) {
      fail("No non-empty user transcript.final");
    }
    if (!assistantFinals.some(item => typeof item.content === "string" && item.content.trim())) {
      fail("No non-empty assistant transcript.final");
    }
    const finalTurnIds = new Set(
      [...userFinals, ...assistantFinals].map(item => item.turnId).filter(Boolean),
    );
    if (
      finalTurnIds.size !== 1 ||
      [...userFinals, ...assistantFinals].some(item => !item.turnId)
    ) {
      fail(`User/assistant transcript.final turnId mismatch: ${JSON.stringify([...finalTurnIds])}`);
    }
    const assistantResponseIds = [...new Set(assistantFinals.map(item => item.responseId))];
    const completedAssistantResponseIds = assistantResponseIds.filter(id => doneResponseIds.has(id));
    const assistantAudioMissing = assistantResponseIds.filter(
      id => !audioBytes[id] || !sampleRates[id],
    );
    if (assistantAudioMissing.length) {
      fail(`Assistant response has no complete sampled audio.delta: ${assistantAudioMissing.join(",")}`);
    }
    const result = {
      label: turn.label ?? null,
      session_id: this.sessionId,
      instance_id: this.instanceId,
      probe_socket_marker: this.probeSocketMarker,
      turn: {
        speech_frames: Math.ceil(pcm.length / FRAME_BYTES),
        tail_ms: tailMs,
        input_bytes: sentBytes,
        input_duration_ms: frames.length * FRAME_MS,
        pcm_duration_ms: Math.round(pcm.length / 2 / SAMPLE_RATE * 1000),
      },
      timing_ms: {
        endpoint_after_speech_frames: endpointAt && speechFramesSentAt ? endpointAt - speechFramesSentAt : null,
        endpoint_after_all_input: endpointAt && sendFinishedAt ? endpointAt - sendFinishedAt : null,
        sent_to_response_started: responseStartedAt && sendFinishedAt ? responseStartedAt - sendFinishedAt : null,
        sent_to_first_audio: firstAudioAt && sendFinishedAt ? firstAudioAt - sendFinishedAt : null,
        first_append_to_response: responseStartedAt ? responseStartedAt - startedAt : null,
      },
      events: eventCounts,
      user_transcripts: userFinals,
      assistant_transcripts: assistantFinals,
      assistant_audio_response_ids_match: completedAssistantResponseIds.length > 0,
      audio_done_response_ids: [...doneResponseIds],
      audio_bytes_by_response: audioBytes,
      audio_sample_rates_by_response: sampleRates,
      turn_ids: [...turnIds],
      response_ids: [...responseIds],
      tool_calls: toolCalls,
      socket_open_after_turn: this.ws.readyState === WebSocket.OPEN,
    };
    if (!assistantFinals.length) fail(`No assistant transcript.final + audio.done pair; result=${JSON.stringify(result)}`);
    return result;
  }

  async close() {
    if (!this.ws || this.ws.readyState === WebSocket.CLOSED) return;
    await new Promise(resolve => {
      const timer = setTimeout(() => {
        try { this.ws.terminate(); } catch {}
        resolve();
      }, 3000);
      this.ws.once("close", () => { clearTimeout(timer); resolve(); });
      this.ws.close(1000, "B8.2 probe finished");
    });
  }
}

async function gatewayHealth() {
  const url = new URL("/api/health", BASE_URL.replace(/^ws/, "http"));
  const response = await fetch(url, { headers: { Authorization: `Bearer ${TOKEN}` } });
  if (!response.ok) fail(`Gateway health endpoint returned ${response.status}`);
  const body = await response.json();
  return {
    status: response.status,
    gateway_status: body.status ?? null,
    input_active: body.voiceInput?.inputActive ?? null,
    clients: body.voiceInput?.clients ?? [],
  };
}

async function historyCount(sessionId) {
  const url = new URL(`/api/conversations/${encodeURIComponent(sessionId)}/messages`, BASE_URL.replace(/^ws/, "http"));
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const body = await response.text();
  if (!response.ok) fail(`Conversation history returned HTTP ${response.status}: ${body.slice(0, 200)}`);
  let value;
  try {
    value = JSON.parse(body);
  } catch {
    fail(`Conversation history returned invalid JSON: ${body.slice(0, 200)}`);
  }
  if (!Array.isArray(value.messages)) fail("Conversation history response has no messages array");
  return {
    status: response.status,
    count: value.messages.length,
    roles: value.messages.map(item => item.role).slice(-8),
    message_keys: value.messages.length ? Object.keys(value.messages.at(-1)).sort() : [],
  };
}

async function run() {
  const input = await readStdin();
  const instanceId = input.instance_id || "tivoo-p68-b82-preflight";
  const report = {
    safety: {
      connects_home_assistant: false,
      connects_esp32: false,
      sends_tts_play: false,
      plays_audio: false,
      audio_delta_discarded: true,
      requests_takeover: false,
    },
    mode: input.mode || "single",
    cases: [],
  };

  if (input.mode === "tail-sweep") {
    for (const test of input.cases || []) {
      const probe = new GatewayConnection(test.session_id, instanceId);
      const item = { label: test.label, tail_ms: test.tail_ms, status: "started" };
      try {
        item.handshake = await probe.connect();
        item.turn = await probe.runTurn(test.turn);
        item.status = "passed";
      } catch (error) {
        item.status = "failed";
        item.error = error.message;
      } finally {
        await probe.close();
      }
      report.cases.push(item);
    }
  } else if (input.mode === "same-socket") {
    const probe = new GatewayConnection(input.session_id, instanceId);
    try {
      const before = await historyCount(input.session_id);
      report.history_before = before;
      report.handshake = await probe.connect();
      const primarySocketMarker = probe.probeSocketMarker;
      const conflict = new GatewayConnection(
        makeId("b82-lease-conflict"),
        `${instanceId}-conflict`,
      );
      try {
        const conflictHandshake = await conflict.connect();
        report.lease_conflict = {
          status: "unexpectedly_acquired_active_lease",
          handshake: conflictHandshake,
        };
      } catch (error) {
        report.lease_conflict = {
          status: error.message.includes("client_occupied") ? "rejected_client_occupied" : error.message.includes("busy") ? "rejected_busy" : "rejected_error",
          error: error.message,
        };
      } finally {
        await conflict.close();
      }
      report.primary_socket_open_after_lease_conflict = probe.ws.readyState === WebSocket.OPEN;
      report.owner_state_after_lease_conflict = await gatewayHealth();
      if (
        !report.owner_state_after_lease_conflict.input_active ||
        report.owner_state_after_lease_conflict.clients.length !== 1
      ) {
        fail("Gateway owner state changed after the rejected client connection");
      }
      if (report.lease_conflict.status !== "rejected_client_occupied") {
        fail(`Second client was not rejected with client_occupied: ${JSON.stringify(report.lease_conflict)}`);
      }
      if (!report.primary_socket_open_after_lease_conflict) {
        fail("Primary WebSocket was closed by the rejected lease attempt");
      }

      report.turns = [];
      const usedTurnIds = new Set();
      const usedResponseIds = new Set();
      for (const turn of input.turns || []) {
        const result = await probe.runTurn(turn);
        if (result.session_id !== input.session_id || result.instance_id !== instanceId) {
          fail("Same-socket turn changed its session_id or client.instance_id");
        }
        if (result.probe_socket_marker !== primarySocketMarker || !result.socket_open_after_turn) {
          fail("Same-socket turn did not retain the original active WebSocket");
        }
        const turnId = result.turn_ids[0];
        const responseId = result.assistant_transcripts[0]?.responseId;
        if (!turnId || usedTurnIds.has(turnId)) fail(`Turn ID was missing or reused: ${turnId}`);
        if (!responseId || usedResponseIds.has(responseId)) fail(`Response ID was missing or reused: ${responseId}`);
        usedTurnIds.add(turnId);
        usedResponseIds.add(responseId);
        report.turns.push(result);
      }
      report.socket_open_after_all_turns = probe.ws.readyState === WebSocket.OPEN;
      report.history_while_open = await historyCount(input.session_id);
      if (report.history_while_open.count < 2 * (input.turns || []).length) {
        fail("Same-socket turns were not fully committed to the conversation journal");
      }
      if (!report.socket_open_after_all_turns) fail("Gateway closed the socket between immediate follow-up turns");
    } finally {
      await probe.close();
    }
    report.history_after_close = await historyCount(input.session_id);
    if (report.history_while_open.count !== report.history_after_close.count) {
      fail("Conversation journal changed while closing the primary WebSocket");
    }

    const reconnect = new GatewayConnection(input.session_id, instanceId);
    try {
      report.reconnect_handshake = await reconnect.connect();
      report.history_after_reconnect = await historyCount(input.session_id);
      if (report.history_after_reconnect.count !== report.history_after_close.count) {
        fail("Same session journal was not restored after reconnect");
      }
      if (input.reconnect_turn) {
        report.reconnect_turn = await reconnect.runTurn(input.reconnect_turn);
      }
    } finally {
      await reconnect.close();
    }
    report.history_after_reconnect_close = await historyCount(input.session_id);
    if (
      input.reconnect_turn &&
      report.history_after_reconnect_close.count < report.history_after_reconnect.count + 2
    ) {
      fail("Reconnect turn did not append its user and assistant messages to history");
    }

    if (input.isolation_session_id) {
      report.isolation_history_before = await historyCount(input.isolation_session_id);
      if (report.isolation_history_before.count !== 0) {
        fail("Isolation test session was not empty before its new connection");
      }
      const isolated = new GatewayConnection(input.isolation_session_id, instanceId);
      try {
        report.isolation_handshake = await isolated.connect();
        report.isolation_history_after_connect = await historyCount(input.isolation_session_id);
        if (report.isolation_history_after_connect.count !== 0) {
          fail("New session inherited history from another session");
        }
        if (input.isolation_turn) report.isolation_turn = await isolated.runTurn(input.isolation_turn);
      } finally {
        await isolated.close();
      }
      report.isolation_history_after_close = await historyCount(input.isolation_session_id);
      if (
        input.isolation_turn &&
        report.isolation_history_after_close.count < 2
      ) {
        fail("Isolation turn did not create an independent user/assistant history pair");
      }
    }
  } else {
    const probe = new GatewayConnection(input.session_id || makeId("b82"), instanceId);
    try {
      report.handshake = await probe.connect();
      report.turn = await probe.runTurn(input.turn);
      report.socket_open_after_turn = probe.ws.readyState === WebSocket.OPEN;
    } finally {
      await probe.close();
    }
  }
  return report;
}

run().then(report => {
  process.stdout.write(JSON.stringify(report, null, 2) + "\n");
}).catch(error => {
  process.stderr.write(JSON.stringify({ error: error.message }) + "\n");
  process.exitCode = 1;
});

"""P6.5 cancellation preflight lifecycle controls."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from homeassistant.components import assist_pipeline, conversation, stt, tts
from homeassistant.components.assist_pipeline.models import (
    Pipeline,
    PipelineEventType,
    PipelineStage,
)
from homeassistant.components.assist_satellite.entity import (
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
)
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry
from pytest_socket import enable_socket

ROOT = Path(__file__).resolve().parents[2]
SHERPA_PYTHON = ROOT / ".venv-sherpa" / "bin" / "python"
FAKE_WYOMING_SERVER = ROOT / "tests" / "helpers" / "p6_5_fake_wyoming_server.py"
LONG_ANSWER = (
    "这是 P6.5b1 正常完成控制组的长文本，用于触发 HA Assist Pipeline 的流式 TTS 输入。"
    "本次测试会通过真实的 HA Wyoming Provider 连接项目中的 P7A Wyoming handler，"
    "由可控模型输出 PCM，再通过 HA TTS Proxy 完整读取音频。" * 24
)


class P65ControlSatellite(AssistSatelliteEntity):
    """Minimal test entity that uses the real HA public pipeline entrypoint."""

    def __init__(self, hass, config_entry) -> None:
        self.hass = hass
        self.platform = SimpleNamespace(config_entry=config_entry)
        self.entity_id = "assist_satellite.p6_5b1_control"
        self.registry_entry = None
        self._conversation_id = None
        self._pipeline_task = None
        self._run_has_tts = False
        self._extra_system_prompt = None
        self._attr_pipeline_entity_id = None
        self._attr_tts_options = {"preferred_format": "wav"}
        self.events = []

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        return AssistSatelliteConfiguration([], [], 0)

    async def async_set_configuration(
        self, config: AssistSatelliteConfiguration
    ) -> None:
        return None

    def on_pipeline_event(self, event) -> None:
        self.events.append(event)

    def async_write_ha_state(self) -> None:
        return None


def _free_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


async def _audio_stream():
    """Yield one short 16 kHz mono PCM utterance."""
    yield b"\x00\x00" * 8_000


async def _send_sse(response: web.StreamResponse, event: dict) -> None:
    payload = json.dumps(event, ensure_ascii=False)
    await response.write(f"data: {payload}\n\n".encode())


@pytest.mark.enable_socket
async def test_normal_pipeline_completion_closes_all_owned_streams(
    hass, enable_custom_integrations, aiohttp_client, monkeypatch, tmp_path
) -> None:
    """A complete Assist run drains its SSE/TTS/Wyoming owners without Stop."""
    enable_socket()
    assert SHERPA_PYTHON.is_file()
    assert FAKE_WYOMING_SERVER.is_file()

    # HA runs on Python 3.14; Wyoming's dependency is pure Python and is
    # supplied by the project's pinned Python 3.11 Sherpa environment.
    monkeypatch.syspath_prepend(
        str(ROOT / ".venv-sherpa" / "lib" / "python3.11" / "site-packages")
    )
    from homeassistant.components.wyoming import tts as wyoming_tts

    port = _free_port()
    trace_path = tmp_path / "p6_5b1_wyoming_trace.jsonl"
    server_env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "services"), os.environ.get("PYTHONPATH", "")]
        ),
    }
    server_process = await asyncio.create_subprocess_exec(
        str(SHERPA_PYTHON),
        str(FAKE_WYOMING_SERVER),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--trace",
        str(trace_path),
        cwd=ROOT,
        env=server_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    server_ready = asyncio.Event()
    p7a_tts_connection_finished = asyncio.Event()
    server_output: list[str] = []

    async def read_server_output() -> None:
        assert server_process.stdout is not None
        while line := await server_process.stdout.readline():
            decoded = line.decode(errors="replace").rstrip()
            server_output.append(decoded)
            if "service_starting" in decoded:
                server_ready.set()
            if (
                "P6_5_TRACE" in decoded
                and '"event": "handler_finished"' in decoded
                and '"last_provider": "tts_stream"' in decoded
            ):
                p7a_tts_connection_finished.set()

    output_task = asyncio.create_task(read_server_output())
    try:
        await asyncio.wait_for(server_ready.wait(), timeout=15)
        assert server_process.returncode is None, server_output

        assert await async_setup_component(hass, "homeassistant", {})

        wyoming_entry = MockConfigEntry(
            domain="wyoming",
            title="P6.5b1 local Sherpa",
            unique_id=f"p6-5b1-{port}",
            data={"host": "127.0.0.1", "port": port},
        )
        wyoming_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(wyoming_entry.entry_id)
        await hass.async_block_till_done()

        stt_engine = stt.async_default_engine(hass)
        tts_engine = tts.async_default_engine(hass)
        assert stt_engine is not None
        assert tts_engine is not None

        stop_calls: list[str] = []
        chat_handler_finished = asyncio.Event()
        wyoming_client_disconnected = asyncio.Event()
        wyoming_disconnect_count = 0
        original_tts_client = wyoming_tts.AsyncTcpClient

        class TrackedWyomingTtsClient(original_tts_client):
            async def disconnect(self):
                nonlocal wyoming_disconnect_count
                wyoming_disconnect_count += 1
                try:
                    await super().disconnect()
                finally:
                    wyoming_client_disconnected.set()

        # Patch the TTS module's client factory, not the shared client class:
        # STT uses a separate TCP connection to the same Wyoming endpoint.
        monkeypatch.setattr(wyoming_tts, "AsyncTcpClient", TrackedWyomingTtsClient)

        async def handle_chat(request: web.Request) -> web.StreamResponse:
            request_body = await request.json()
            response = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Connection": "close",
                },
            )
            await response.prepare(request)
            await _send_sse(
                response,
                {
                    "type": "session_id",
                    "data": None,
                    "session_id": request_body["session_id"],
                },
            )
            split_at = len(LONG_ANSWER) // 2
            await _send_sse(response, {"type": "plain", "data": LONG_ANSWER[:split_at]})
            await _send_sse(response, {"type": "plain", "data": LONG_ANSWER[split_at:]})
            await _send_sse(response, {"type": "end", "data": ""})
            await response.write_eof()
            chat_handler_finished.set()
            return response

        async def handle_stop(request: web.Request) -> web.Response:
            stop_calls.append(request.match_info["session_id"])
            return web.json_response({"status": "ok", "data": {}})

        astrbot_app = web.Application()
        astrbot_app.router.add_post("/api/v1/chat", handle_chat)
        astrbot_app.router.add_post(
            "/api/v1/chat/sessions/{session_id}/stop", handle_stop
        )
        astrbot_client = await aiohttp_client(astrbot_app)
        base_url = str(astrbot_client.make_url("/")).rstrip("/")

        from custom_components.astrbot.api import AstrBotApiClient

        sse_reader_closed = asyncio.Event()
        original_async_chat = AstrBotApiClient.async_chat

        @asynccontextmanager
        async def tracked_async_chat(self, *args, **kwargs):
            try:
                async with original_async_chat(self, *args, **kwargs) as response:
                    yield response
            finally:
                sse_reader_closed.set()

        monkeypatch.setattr(AstrBotApiClient, "async_chat", tracked_async_chat)

        astrbot_entry = MockConfigEntry(
            domain="astrbot",
            title="AstrBot",
            unique_id="astrbot",
            data={
                "base_url": base_url,
                "api_key": "test-secret-value",
                "api_key_id": "p6-5b1-test-key",
            },
        )
        astrbot_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(astrbot_entry.entry_id)
        await hass.async_block_till_done()
        agent = conversation.async_get_agent(hass, "conversation.astrbot")
        assert agent is not None
        assert agent.supports_streaming is True

        pipeline = Pipeline(
            id="p6-5b1-normal-control",
            conversation_engine="conversation.astrbot",
            conversation_language="zh-CN",
            language="zh-CN",
            name="P6.5b1 normal completion",
            stt_engine=stt_engine,
            stt_language="zh-CN",
            tts_engine=tts_engine,
            tts_language="zh-CN",
            tts_voice="0",
            wake_word_entity=None,
            wake_word_id=None,
        )
        monkeypatch.setattr(
            assist_pipeline, "async_get_pipeline", lambda *_args, **_kwargs: pipeline
        )

        # Capture the actual TTS-cache producer task and the text generator it owns.
        proxy_tasks: list[asyncio.Task] = []
        lifecycle: list[tuple[str, float]] = []

        def mark(event: str) -> None:
            lifecycle.append((event, asyncio.get_running_loop().time()))

        original_hass_background = hass.async_create_background_task

        def track_hass_background(*args, **kwargs):
            task = original_hass_background(*args, **kwargs)
            name = args[1] if len(args) > 1 else kwargs.get("name", "")
            if name.startswith("tts_load_data_into_cache"):
                proxy_tasks.append(task)
                mark("tts_cache_producer_created")
                task.add_done_callback(lambda _task: mark("tts_cache_producer_done"))
            return task

        monkeypatch.setattr(hass, "async_create_background_task", track_hass_background)

        manager = hass.data[tts.DATA_TTS_MANAGER]
        tts_text_generators = []
        tts_caches = []
        original_cache_stream = manager.async_cache_message_stream_in_memory

        def track_cache_stream(**kwargs):
            tts_text_generators.append(kwargs["message_stream"])
            mark("tts_text_stream_created")
            cache = original_cache_stream(**kwargs)
            tts_caches.append(cache)
            return cache

        monkeypatch.setattr(
            manager, "async_cache_message_stream_in_memory", track_cache_stream
        )

        config_entry_tasks: dict[str, list[asyncio.Task]] = {}
        original_entry_background = wyoming_entry.async_create_background_task

        def track_entry_background(*args, **kwargs):
            task = original_entry_background(*args, **kwargs)
            name = args[2] if len(args) > 2 else kwargs.get("name", "")
            config_entry_tasks.setdefault(name, []).append(task)
            mark(f"{name}_created")
            task.add_done_callback(
                lambda _task, task_name=name: mark(f"{task_name}_done")
            )
            return task

        monkeypatch.setattr(
            wyoming_entry, "async_create_background_task", track_entry_background
        )

        satellite = P65ControlSatellite(hass, wyoming_entry)
        mark("pipeline_start")
        await satellite.async_accept_pipeline_from_satellite(
            _audio_stream(),
            start_stage=PipelineStage.STT,
            end_stage=PipelineStage.TTS,
            context=Context(user_id="p6-5b1-ha-user"),
        )
        mark("pipeline_done")

        await asyncio.wait_for(sse_reader_closed.wait(), timeout=5)
        await asyncio.wait_for(chat_handler_finished.wait(), timeout=5)
        assert satellite._pipeline_task is None
        assert any(
            event.type is PipelineEventType.RUN_END for event in satellite.events
        )
        assert any(
            event.type is PipelineEventType.STT_END for event in satellite.events
        )
        assert any(
            event.type is PipelineEventType.INTENT_END for event in satellite.events
        )
        assert any(
            event.type is PipelineEventType.TTS_END for event in satellite.events
        )
        assert not any(
            event.type is PipelineEventType.ERROR for event in satellite.events
        )
        assert stop_calls == []

        tts_end = next(
            event
            for event in satellite.events
            if event.type is PipelineEventType.TTS_END
        )
        token = tts_end.data["tts_output"]["token"]
        assert tts.async_get_stream(hass, token) is not None

        web_client = await aiohttp_client(hass.http.app)
        mark("tts_proxy_get_start")
        response = await web_client.get(f"/api/tts_proxy/{token}")
        assert response.status == 200
        assert response.content_type == "audio/x-wav"
        audio_data = await response.read()
        mark("tts_proxy_get_done")
        await asyncio.wait_for(wyoming_client_disconnected.wait(), timeout=5)
        assert wyoming_disconnect_count == 1
        assert audio_data.startswith(b"RIFF")
        assert len(audio_data) > 44

        assert len(tts_text_generators) == 1
        assert tts_text_generators[0].ag_frame is None
        assert len(tts_caches) == 1
        cache = tts_caches[0]
        assert cache._result_data == audio_data
        assert cache._loading_error is None
        assert len(proxy_tasks) == 1
        assert proxy_tasks[0].done()
        assert not proxy_tasks[0].cancelled()
        assert proxy_tasks[0].exception() is None

        pipeline_tasks = config_entry_tasks.get(f"{satellite.entity_id}_pipeline", [])
        assert len(pipeline_tasks) == 1
        assert pipeline_tasks[0].done()
        assert not pipeline_tasks[0].cancelled()
        assert pipeline_tasks[0].exception() is None

        wyoming_writer_tasks = config_entry_tasks.get("wyoming tts write", [])
        assert len(wyoming_writer_tasks) == 1
        assert wyoming_writer_tasks[0].done()
        assert not wyoming_writer_tasks[0].cancelled()
        assert wyoming_writer_tasks[0].exception() is None

        await asyncio.wait_for(p7a_tts_connection_finished.wait(), timeout=5)
        traces = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cleanup = [item for item in traces if item["event"] == "tts_session_cleanup"]
        assert cleanup
        assert cleanup[-1]["input_task_done"] is True
        assert cleanup[-1]["worker_task_done"] is True
        assert cleanup[-1]["input_stopped"] is True
        assert cleanup[-1]["failed"] is False
        assert cleanup[-1]["text_chars"] == len(LONG_ANSWER)

        collect = [item for item in traces if item["event"] == "tts_collect_complete"]
        assert collect
        assert collect[-1]["task_done"] is True
        assert collect[-1]["task_cancelled"] is False

        resets = [item for item in traces if item["event"] == "request_reset"]
        assert resets
        assert resets[-1]["previous_provider"] == "tts_stream"
        assert resets[-1]["provider_after_reset"] is None
        assert resets[-1]["tts_task_pending"] is False

        stt_handlers = [
            item
            for item in traces
            if item["event"] == "handler_finished"
            and item.get("last_provider") == "stt"
        ]
        assert stt_handlers

        handler = [
            item
            for item in traces
            if item["event"] == "handler_finished"
            and item.get("last_provider") == "tts_stream"
        ]
        assert handler
        assert handler[-1]["tts_task_pending"] is False
        assert server_process.returncode is None

        # The service remains listening; only this completed request connection closes.
        lifecycle_names = [name for name, _timestamp in lifecycle]
        assert lifecycle_names.index("pipeline_start") < lifecycle_names.index(
            "pipeline_done"
        )
        assert lifecycle_names.index("pipeline_done") < lifecycle_names.index(
            "tts_proxy_get_start"
        )
        assert lifecycle_names.index("tts_proxy_get_start") < lifecycle_names.index(
            "tts_proxy_get_done"
        )
        assert lifecycle_names.index(
            "tts_cache_producer_created"
        ) < lifecycle_names.index("tts_cache_producer_done")
        assert lifecycle_names.index(
            "wyoming tts write_created"
        ) < lifecycle_names.index("wyoming tts write_done")

        assert await hass.config_entries.async_unload(astrbot_entry.entry_id)
        assert await hass.config_entries.async_unload(wyoming_entry.entry_id)
        await hass.async_block_till_done()
    finally:
        if server_process.returncode is None:
            server_process.send_signal(signal.SIGTERM)
            await asyncio.wait_for(server_process.wait(), timeout=5)
        output_task.cancel()
        await asyncio.gather(output_task, return_exceptions=True)

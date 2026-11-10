from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sherpa_wyoming import healthcheck
from wyoming.info import (
    AsrModel,
    AsrProgram,
    Attribution,
    Info,
    TtsProgram,
    TtsVoice,
    WakeModel,
    WakeProgram,
)

_ATTRIBUTION = Attribution(name="test", url="https://example.invalid")


def _valid_info() -> Info:
    return Info(
        wake=[
            WakeProgram(
                name="wake",
                attribution=_ATTRIBUTION,
                installed=True,
                description=None,
                version=None,
                models=[
                    WakeModel(
                        name="tivoo-wake",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description=None,
                        version=None,
                        languages=["zh-CN"],
                        phrase="test phrase",
                    )
                ],
            )
        ],
        asr=[
            AsrProgram(
                name="asr",
                attribution=_ATTRIBUTION,
                installed=True,
                description=None,
                version=None,
                models=[
                    AsrModel(
                        name="paraformer",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description=None,
                        version=None,
                        languages=["zh-CN"],
                    )
                ],
            )
        ],
        tts=[
            TtsProgram(
                name="tts",
                attribution=_ATTRIBUTION,
                installed=True,
                description=None,
                version=None,
                voices=[
                    TtsVoice(
                        name="0",
                        attribution=_ATTRIBUTION,
                        installed=True,
                        description=None,
                        version=None,
                        languages=["zh-CN"],
                    )
                ],
            )
        ],
    )


def test_check_health_sends_describe_and_accepts_three_installed_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {}

    class FakeClient:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            state["host"] = host
            state["port"] = port
            state["kwargs"] = kwargs

        async def connect(self) -> None:
            state["connected"] = True

        async def write_event(self, event: object) -> None:
            state["request"] = event

        async def read_event(self) -> object:
            return _valid_info().event()

        async def disconnect(self) -> None:
            state["disconnected"] = True

    monkeypatch.setattr(healthcheck, "AsyncTcpClient", FakeClient)

    asyncio.run(healthcheck.check_health("127.0.0.1", 10400))

    assert state["host"] == "127.0.0.1"
    assert state["port"] == 10400
    assert state["connected"] is True
    assert state["request"].type == "describe"
    assert state["disconnected"] is True


@pytest.mark.parametrize(
    ("field", "providers"),
    [
        ("wake", []),
        ("asr", []),
        ("tts", []),
        (
            "wake",
            [
                WakeProgram(
                    name="wake",
                    attribution=_ATTRIBUTION,
                    installed=False,
                    description=None,
                    version=None,
                    models=[],
                )
            ],
        ),
        (
            "wake",
            [
                WakeProgram(
                    name="wake",
                    attribution=_ATTRIBUTION,
                    installed=True,
                    description=None,
                    version=None,
                    models=[
                        WakeModel(
                            name="tivoo-wake",
                            attribution=_ATTRIBUTION,
                            installed=False,
                            description=None,
                            version=None,
                            languages=["zh-CN"],
                            phrase="test phrase",
                        )
                    ],
                )
            ],
        ),
    ],
)
def test_check_health_rejects_missing_or_uninstalled_provider(
    monkeypatch: pytest.MonkeyPatch, field: str, providers: list[object]
) -> None:
    info = _valid_info()
    setattr(info, field, providers)

    class FakeClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def write_event(self, _: object) -> None:
            return None

        async def read_event(self) -> object:
            return info.event()

        async def disconnect(self) -> None:
            return None

    monkeypatch.setattr(healthcheck, "AsyncTcpClient", FakeClient)

    with pytest.raises(healthcheck.HealthcheckError, match=field):
        asyncio.run(healthcheck.check_health("127.0.0.1", 10400))


def test_check_health_rejects_tcp_connection_without_wyoming_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def write_event(self, _: object) -> None:
            return None

        async def read_event(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    monkeypatch.setattr(healthcheck, "AsyncTcpClient", FakeClient)

    with pytest.raises(healthcheck.HealthcheckError, match="Info"):
        asyncio.run(healthcheck.check_health("127.0.0.1", 10400))


def test_healthcheck_module_is_in_runtime_package() -> None:
    assert Path(healthcheck.__file__).is_file()

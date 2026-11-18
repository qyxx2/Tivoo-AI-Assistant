from __future__ import annotations

import argparse
import asyncio
import sys

from wyoming.client import AsyncTcpClient
from wyoming.info import Describe, Info


class HealthcheckError(RuntimeError):
    """The Wyoming endpoint did not publish all installed Providers."""


def validate_info(info: Info, *, device_endpoint: bool = False) -> None:
    """Require an installed program and installed model/voice for each platform."""

    if device_endpoint:
        if (
            info.wake or info.tts or info.intent or info.handle or info.satellite
            or len(info.asr) != 1
            or info.asr[0].name != "Sherpa ONNX Paraformer Device Endpoint"
            or info.asr[0].requires_external_vad
            or info.asr[0].supports_transcript_streaming
            or not info.asr[0].installed
            or not any(model.installed for model in info.asr[0].models)
        ):
            raise HealthcheckError("device endpoint ASR-only contract mismatch")
        return

    checks = (
        ("wake", info.wake, "models"),
        ("asr", info.asr, "models"),
        ("tts", info.tts, "voices"),
    )
    for name, programs, child_attribute in checks:
        installed = any(
            program.installed
            and any(child.installed for child in getattr(program, child_attribute, ()))
            for program in programs
        )
        if not installed:
            raise HealthcheckError(
                f"{name} Provider is missing or has no installed model/voice"
            )


async def check_health(
    host: str = "127.0.0.1", port: int = 10400, timeout: float = 5.0,
    *, device_endpoint: bool = False
) -> None:
    """Send a Wyoming Describe request and validate the returned Info."""

    client = AsyncTcpClient(
        host,
        port,
        connect_timeout=timeout,
        read_timeout=timeout,
    )
    try:
        await client.connect()
        await client.write_event(Describe().event())
        response = await client.read_event()
        if response is None:
            raise HealthcheckError("Wyoming endpoint closed without returning Info")
        if not Info.is_type(response.type):
            raise HealthcheckError(
                f"Wyoming Describe returned {response.type!r}, not Info"
            )
        validate_info(Info.from_event(response), device_endpoint=device_endpoint)
    except HealthcheckError:
        raise
    except Exception as exc:
        raise HealthcheckError(
            f"Wyoming Describe check failed ({type(exc).__name__})"
        ) from exc
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that all three Sherpa Wyoming Providers are installed."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10400)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--device-stt-port", type=int)
    args = parser.parse_args(argv)

    try:
        async def check_all():
            await asyncio.gather(
                check_health(args.host, args.port, args.timeout),
                *([check_health(args.host, args.device_stt_port, args.timeout,
                               device_endpoint=True)] if args.device_stt_port is not None else []),
            )
        asyncio.run(check_all())
    except Exception as exc:  # noqa: BLE001
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1

    print("healthy: wake, asr and tts Providers are installed" + ("; device ASR endpoint ready" if args.device_stt_port else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

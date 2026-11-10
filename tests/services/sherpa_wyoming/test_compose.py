from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "deploy/nas/compose/sherpa-wyoming.yml"


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_contains_one_private_ghcr_service_and_no_host_ports() -> None:
    compose = _compose()

    assert set(compose["services"]) == {"sherpa-wyoming"}
    service = compose["services"]["sherpa-wyoming"]
    assert re.fullmatch(
        r"ghcr\.io/qyxx2/tivoo-sherpa-wyoming:\$\{IMAGE_TAG[^}]*\}",
        service["image"],
    )
    assert "build" not in service
    assert "ports" not in service
    assert service["expose"] == ["10400"]
    assert "10500" not in COMPOSE_PATH.read_text(encoding="utf-8")


def test_compose_uses_existing_external_ha_network() -> None:
    compose = _compose()

    assert set(compose["networks"]) == {"ha"}
    network = compose["networks"]["ha"]
    assert network["external"] is True
    assert network["name"].startswith("${HA_DOCKER_NETWORK")


def test_compose_persists_all_three_model_directories() -> None:
    service = _compose()["services"]["sherpa-wyoming"]
    mounts = service["volumes"]

    assert {mount["target"] for mount in mounts} == {
        "/models/kws",
        "/models/stt",
        "/models/tts",
    }
    assert all(mount["type"] == "bind" for mount in mounts)
    assert all(mount["source"].startswith("${NAS_MODELS_DIR") for mount in mounts)


def test_compose_healthcheck_uses_wyoming_describe_module() -> None:
    service = _compose()["services"]["sherpa-wyoming"]

    assert service["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-m",
        "sherpa_wyoming.healthcheck",
        "--host",
        "127.0.0.1",
        "--port",
        "10400",
    ]
    assert service["healthcheck"]["start_period"] == "180s"


def test_compose_passes_only_the_runtime_settings_needed_by_service() -> None:
    service = _compose()["services"]["sherpa-wyoming"]

    assert service["environment"]["WAKE_WORD_PHRASE"].startswith("${WAKE_WORD_PHRASE")
    assert service["environment"]["MODELS_DIR"] == "/models"
    assert service["environment"]["PORT"] == 10400

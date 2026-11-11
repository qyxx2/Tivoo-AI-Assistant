"""Tests for the Tivoo Home Assistant integration setup."""

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant.common import MockConfigEntry

from homeassistant import loader

DOMAIN = "tivoo"
DEFAULT_MEDIA_DIRECTORY = "pixelart"


async def _submit_user_flow(hass, media_directory=DEFAULT_MEDIA_DIRECTORY):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "form"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"media_directory": media_directory, "esp32_host": "127.0.0.1"},
    )


async def test_manifest_is_a_single_configurable_service(
    hass, enable_custom_integrations
):
    integration = await loader.async_get_integration(hass, DOMAIN)

    assert integration.manifest["name"] == "Tivoo"
    assert integration.manifest["config_flow"] is True
    assert integration.manifest["single_config_entry"] is True
    assert integration.manifest["integration_type"] == "service"


async def test_config_flow_uses_pixelart_as_default_media_directory(
    hass, socket_enabled
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "form"

    marker = next(
        marker
        for marker in result["data_schema"].schema
        if marker.schema == "media_directory"
    )
    assert marker.default() == DEFAULT_MEDIA_DIRECTORY

    created = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"esp32_host": "127.0.0.1"}
    )
    assert created["type"] == "create_entry"
    assert created["data"] == {
        "media_directory": DEFAULT_MEDIA_DIRECTORY,
        "esp32_host": "127.0.0.1",
        "tivoo_bluetooth_mac": "11:75:58:97:49:98",
    }


async def test_config_flow_saves_custom_media_directory(hass, socket_enabled):
    result = await _submit_user_flow(hass, "media/tivoo")

    assert result["type"] == "create_entry"
    assert result["data"] == {
        "media_directory": "media/tivoo",
        "esp32_host": "127.0.0.1",
        "tivoo_bluetooth_mac": "11:75:58:97:49:98",
    }


async def test_config_flow_rejects_a_second_instance(hass, socket_enabled):
    first = await _submit_user_flow(hass)
    assert first["type"] == "create_entry"

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert second["type"] == "abort"
    assert second["reason"] == "single_instance_allowed"


async def test_config_entry_setup_and_unload_follow_service_lifecycle(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": DEFAULT_MEDIA_DIRECTORY},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "stop_countdown")
    assert hass.services.has_service(DOMAIN, "set_volume")
    assert hass.services.has_service(DOMAIN, "show_image")
    assert hass.services.has_service(DOMAIN, "play_animation")
    assert set(hass.services.async_services()[DOMAIN]) == {
        "stop_countdown",
        "set_volume",
        "set_expression",
        "show_text",
        "start_countdown",
        "set_brightness",
        "show_image",
        "play_animation",
    }
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime["media_directory"] == hass.config.path(DEFAULT_MEDIA_DIRECTORY)
    assert runtime["connection_adapter"].states == {
        "control": "unavailable",
        "diagnostic": "unavailable",
    }
    assert "esp32_host" not in entry.data
    assert entry.version == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert runtime["connection_adapter"].states == {
        "control": "unavailable",
        "diagnostic": "unavailable",
    }
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "stop_countdown")
    assert not hass.services.has_service(DOMAIN, "set_volume")
    assert not hass.services.has_service(DOMAIN, "show_image")
    assert not hass.services.has_service(DOMAIN, "play_animation")
    assert DOMAIN not in hass.data


@pytest.mark.parametrize(
    "media_directory", ["", "/tmp/tivoo", "../outside", "media/../outside"]
)
async def test_config_flow_rejects_media_directory_outside_config_root(
    hass, media_directory
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    configured = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"media_directory": media_directory, "esp32_host": "127.0.0.1"},
    )

    assert configured["type"] == "form"
    assert configured["errors"] == {"media_directory": "invalid_path"}


async def test_config_and_service_descriptions_are_available(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": DEFAULT_MEDIA_DIRECTORY},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    config = await async_get_translations(hass, "en", "config", [DOMAIN])
    services = await async_get_all_descriptions(hass)

    assert config["component.tivoo.config.step.user.title"] == "Configure Tivoo"
    assert services[DOMAIN]["stop_countdown"]["name"] == "Stop countdown"
    assert services[DOMAIN]["set_volume"]["name"] == "Set volume"
    assert services[DOMAIN]["stop_countdown"]["fields"] == {}
    volume = services[DOMAIN]["set_volume"]["fields"]["volume"]
    assert volume["required"] is True
    assert volume["selector"]["number"]["min"] == 0
    assert volume["selector"]["number"]["max"] == 100
    assert volume["selector"]["number"]["step"] == 1

    assert set(services[DOMAIN]) == {
        "stop_countdown",
        "set_volume",
        "set_expression",
        "show_text",
        "start_countdown",
        "set_brightness",
        "show_image",
        "play_animation",
    }
    for service in ("show_image", "play_animation"):
        fields = services[DOMAIN][service]["fields"]
        assert set(fields) == {"file", "time"}
        assert fields["file"]["required"] is True
        assert fields["time"]["required"] is False
        assert fields["time"]["selector"]["number"]["min"] == 0
        assert fields["time"]["selector"]["number"]["max"] == 65535
    assert services[DOMAIN]["set_expression"]["fields"]["name"]["required"] is True
    assert set(services[DOMAIN]["show_text"]["fields"]) == {
        "value",
        "color",
        "background",
        "speed",
        "step",
        "font_size",
        "font",
    }
    assert services[DOMAIN]["show_text"]["fields"]["value"]["required"] is True
    assert (
        services[DOMAIN]["start_countdown"]["fields"]["countdown"]["required"] is True
    )
    assert services[DOMAIN]["set_brightness"]["fields"]["value"]["required"] is True


async def test_config_flow_rejects_non_ipv4_esp32_host(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    configured = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"media_directory": DEFAULT_MEDIA_DIRECTORY, "esp32_host": "::1"},
    )

    assert configured["type"] == "form"
    assert configured["errors"] == {"esp32_host": "invalid_ipv4"}


async def test_config_flow_rejects_invalid_tivoo_bluetooth_mac(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    configured = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "media_directory": DEFAULT_MEDIA_DIRECTORY,
            "esp32_host": "127.0.0.1",
            "tivoo_bluetooth_mac": "not-a-mac",
        },
    )

    assert configured["type"] == "form"
    assert configured["errors"] == {"tivoo_bluetooth_mac": "invalid_mac"}


async def test_legacy_entry_migration_preserves_media_without_guessing_host(hass):
    import importlib

    integration = importlib.import_module("custom_components.tivoo")
    migrate = getattr(integration, "async_migrate_entry", None)
    assert callable(migrate), "Tivoo Config Entry migration must be implemented"

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={"media_directory": "media/tivoo"},
        version=1,
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    assert await migrate(hass, entry)
    assert entry.version == 2
    assert entry.data == {
        "media_directory": "media/tivoo",
        "tivoo_bluetooth_mac": "11:75:58:97:49:98",
    }
    assert "esp32_host" not in entry.data


async def test_reconfigure_adds_explicit_host_and_preserves_existing_media(
    hass, socket_enabled
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tivoo",
        data={
            "media_directory": "media/tivoo",
            "esp32_host": "127.0.0.1",
            "tivoo_bluetooth_mac": "11:75:58:97:49:98",
        },
        version=2,
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] == "form"
    updated = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "media_directory": "media/tivoo",
            "esp32_host": "127.0.0.1",
            "tivoo_bluetooth_mac": "11:75:58:97:49:98",
        },
    )

    assert updated["type"] == "abort"
    assert entry.data["media_directory"] == "media/tivoo"
    assert entry.data["esp32_host"] == "127.0.0.1"
    assert entry.data["tivoo_bluetooth_mac"] == "11:75:58:97:49:98"

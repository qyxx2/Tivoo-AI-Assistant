"""Tests for the AstrBot Home Assistant integration baseline."""

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant.common import MockConfigEntry

from homeassistant import loader

DOMAIN = "astrbot"
BASE_URL = "http://astrbot.example:6185"
API_KEY = "test-secret-value"
API_KEY_ID = "key-123"


def _user_input(**overrides):
    data = {
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "api_key_id": API_KEY_ID,
    }
    data.update(overrides)
    return data


async def _submit_user_flow(hass, **overrides):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == "form"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_user_input(**overrides)
    )


async def test_manifest_is_a_single_configurable_service(
    hass, enable_custom_integrations
):
    integration = await loader.async_get_integration(hass, DOMAIN)

    assert integration.manifest["name"] == "AstrBot Conversation Agent"
    assert integration.manifest["config_flow"] is True
    assert integration.manifest["single_config_entry"] is True
    assert integration.manifest["integration_type"] == "service"


async def test_config_flow_exposes_only_base_url_key_and_key_id(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    fields = {
        marker.schema: field for marker, field in result["data_schema"].schema.items()
    }
    assert set(fields) == {"base_url", "api_key", "api_key_id"}
    assert isinstance(fields["api_key"], selector.TextSelector)
    assert fields["api_key"].config["type"] == "password"


async def test_config_flow_translations_are_available(hass):
    translations = await async_get_translations(hass, "en", "config", [DOMAIN])

    assert (
        translations["component.astrbot.config.step.user.title"] == "Connect to AstrBot"
    )
    assert "component.astrbot.config.error.invalid_url" in translations
    assert "component.astrbot.config.abort.single_instance_allowed" in translations


async def test_config_flow_saves_credentials_without_editable_username(hass, caplog):
    result = await _submit_user_flow(hass, base_url=f"{BASE_URL}/")

    assert result["type"] == "create_entry"
    assert result["title"] == "AstrBot"
    assert result["data"] == {
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "api_key_id": API_KEY_ID,
    }
    assert API_KEY not in caplog.text


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://astrbot.example:6185",
        "http:///missing-host",
        "http://astrbot.example:6185/api/v1/chat",
        "http://astrbot.example:6185/proxy/api/v1/chat",
        "http://user:password@astrbot.example:6185",
        "http://astrbot.example:6185?token=secret",
        "http://astrbot.example:6185?",
        "http://astrbot.example:6185#",
        "http://astrbot.example:99999",
    ],
)
async def test_config_flow_rejects_invalid_base_urls(hass, base_url):
    result = await _submit_user_flow(hass, base_url=base_url)

    assert result["type"] == "form"
    assert result["errors"] == {"base_url": "invalid_url"}


async def test_config_flow_accepts_an_ipv6_base_url(hass):
    result = await _submit_user_flow(hass, base_url="https://[2001:db8::1]:6185/")

    assert result["type"] == "create_entry"
    assert result["data"]["base_url"] == "https://[2001:db8::1]:6185"


async def test_config_flow_requires_api_key_and_key_id(hass):
    result = await _submit_user_flow(hass, api_key="  ", api_key_id="  ")

    assert result["type"] == "form"
    assert result["errors"] == {
        "api_key": "required",
        "api_key_id": "required",
    }


async def test_config_flow_rejects_a_second_instance(hass):
    first = await _submit_user_flow(hass)
    assert first["type"] == "create_entry"

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert second["type"] == "abort"
    assert second["reason"] == "single_instance_allowed"


async def test_config_entry_can_setup_and_unload(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AstrBot",
        data={"base_url": BASE_URL, "api_key": API_KEY, "api_key_id": API_KEY_ID},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED

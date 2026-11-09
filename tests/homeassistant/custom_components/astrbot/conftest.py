"""Shared HA Core setup for AstrBot integration tests."""

import pytest
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
async def setup_homeassistant_core(hass):
    """Mirror the Core component that is loaded during a normal HA startup."""
    assert await async_setup_component(hass, "homeassistant", {})

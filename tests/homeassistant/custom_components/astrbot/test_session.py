"""Tests for the AstrBot single-user session identity and Store."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid1, uuid4

import pytest
from custom_components.astrbot import session as session_module
from custom_components.astrbot.const import (
    DOMAIN,
    SESSION_STORE_KEY,
    SESSION_STORE_VERSION,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.storage import Store
from pytest_homeassistant.common import MockConfigEntry

BASE_URL = "http://astrbot.example:6185"
API_KEY = "test-secret-value"
API_KEY_ID = "key-123"
INITIAL_TIME = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)
STORAGE_FIELDS = {
    "version",
    "base_url",
    "api_key_id",
    "username",
    "session_id",
    "created_at",
    "last_activity_at",
}


class FakeClock:
    def __init__(self):
        self.now = INITIAL_TIME

    def __call__(self):
        return self.now

    def advance(self, delta: timedelta):
        self.now += delta


@pytest.fixture
def clock(monkeypatch):
    fake_clock = FakeClock()
    monkeypatch.setattr(session_module.dt_util, "utcnow", fake_clock)
    return fake_clock


def _entry_data(**overrides):
    data = {
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "api_key_id": API_KEY_ID,
    }
    data.update(overrides)
    return data


async def _setup_entry(hass, data=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AstrBot",
        data=data or _entry_data(),
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    return entry, hass.data[DOMAIN][entry.entry_id]["session_manager"]


async def _reload_entry(hass, entry, **changes):
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, data={**entry.data, **changes})
    assert await hass.config_entries.async_setup(entry.entry_id)
    return hass.data[DOMAIN][entry.entry_id]["session_manager"]


async def _stored_record(hass):
    return await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_load()


def _valid_record(**overrides):
    data = {
        "version": 1,
        "base_url": BASE_URL,
        "api_key_id": API_KEY_ID,
        "username": "api_key:key-123",
        "session_id": str(uuid4()),
        "created_at": INITIAL_TIME.isoformat(),
        "last_activity_at": INITIAL_TIME.isoformat(),
    }
    data.update(overrides)
    return data


async def test_username_is_derived_from_api_key_id(hass, clock):
    _, manager = await _setup_entry(hass)

    assert manager.username == "api_key:key-123"
    session_id = manager.get_session_id()
    assert UUID(session_id).version == 4


async def test_candidate_is_not_saved_until_astrbot_accepts_matching_session(
    hass, clock
):
    _, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()

    assert await _stored_record(hass) is None

    with pytest.raises(ValueError):
        await manager.async_confirm_session(str(uuid4()))
    assert await _stored_record(hass) is None

    await manager.async_confirm_session(session_id)
    record = await _stored_record(hass)

    assert set(record) == STORAGE_FIELDS
    assert record == {
        "version": 1,
        "base_url": BASE_URL,
        "api_key_id": API_KEY_ID,
        "username": "api_key:key-123",
        "session_id": session_id,
        "created_at": INITIAL_TIME.isoformat(),
        "last_activity_at": INITIAL_TIME.isoformat(),
    }


@pytest.mark.parametrize(
    ("idle_time", "reuses_session"),
    [
        (timedelta(hours=23, minutes=59, seconds=59), True),
        (timedelta(hours=24), False),
        (timedelta(hours=25), False),
    ],
)
async def test_session_expires_at_24_hours_of_inactivity(
    hass, clock, idle_time, reuses_session
):
    _, manager = await _setup_entry(hass)
    first_session_id = manager.get_session_id()
    await manager.async_confirm_session(first_session_id)

    clock.advance(idle_time)
    current_session_id = manager.get_session_id()

    assert (current_session_id == first_session_id) is reuses_session
    assert UUID(current_session_id).version == 4


async def test_each_accepted_request_slides_the_24_hour_idle_window(hass, clock):
    _, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()

    clock.advance(timedelta(hours=8))
    await manager.async_confirm_session(session_id)
    first_record = await _stored_record(hass)

    clock.advance(timedelta(hours=23))
    assert manager.get_session_id() == session_id
    await manager.async_confirm_session(session_id)
    second_record = await _stored_record(hass)

    assert second_record["session_id"] == session_id
    assert second_record["created_at"] == first_record["created_at"]
    assert second_record["last_activity_at"] == clock.now.isoformat()

    clock.advance(timedelta(hours=24))
    assert manager.get_session_id() != session_id


async def test_store_restores_the_same_session_after_entry_reload(hass, clock):
    entry, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()
    await manager.async_confirm_session(session_id)

    restored_manager = await _reload_entry(hass, entry)

    assert restored_manager.username == "api_key:key-123"
    assert restored_manager.get_session_id() == session_id


async def test_ha_conversation_identity_does_not_control_astrbot_session(hass, clock):
    entry, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()
    await manager.async_confirm_session(session_id)

    # HA can create a new short-lived conversation while the P3 Store remains stable.
    restored_manager = await _reload_entry(hass, entry)
    assert restored_manager.get_session_id() == session_id


@pytest.mark.parametrize(
    ("changes", "expected_username"),
    [
        ({"base_url": "https://astrbot.example:6185"}, "api_key:key-123"),
        ({"api_key_id": "key-456"}, "api_key:key-456"),
    ],
)
async def test_base_url_or_api_key_id_change_creates_a_new_session(
    hass, clock, changes, expected_username
):
    entry, manager = await _setup_entry(hass)
    old_session_id = manager.get_session_id()
    await manager.async_confirm_session(old_session_id)

    updated_manager = await _reload_entry(hass, entry, **changes)
    new_session_id = updated_manager.get_session_id()

    assert new_session_id != old_session_id
    assert UUID(new_session_id).version == 4
    assert updated_manager.username == expected_username


async def test_replacing_secret_for_same_key_id_keeps_the_session(hass, clock):
    entry, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()
    await manager.async_confirm_session(session_id)

    updated_manager = await _reload_entry(hass, entry, api_key="replacement-secret")

    assert updated_manager.get_session_id() == session_id
    record = await _stored_record(hass)
    assert "api_key" not in record
    assert "replacement-secret" not in str(record)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 0),
        ("base_url", "https://other.example"),
        ("api_key_id", "old-key"),
        ("username", "ha-user"),
        ("session_id", "not-a-uuid"),
        ("session_id", str(uuid1())),
        ("created_at", "not-a-date"),
        ("last_activity_at", "2026-11-09T06:00:00"),
        ("last_activity_at", "not-a-date"),
    ],
)
async def test_invalid_or_foreign_store_record_is_not_reused(hass, clock, field, value):
    invalid_session_id = str(uuid4())
    record = _valid_record(session_id=invalid_session_id)
    record[field] = value
    await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_save(record)

    _, manager = await _setup_entry(hass)
    new_session_id = manager.get_session_id()

    assert new_session_id != invalid_session_id
    assert UUID(new_session_id).version == 4


@pytest.mark.parametrize("missing_field", sorted(STORAGE_FIELDS))
async def test_store_record_missing_required_field_is_not_reused(
    hass, clock, missing_field
):
    invalid_session_id = str(uuid4())
    record = _valid_record(session_id=invalid_session_id)
    record.pop(missing_field)
    await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_save(record)

    _, manager = await _setup_entry(hass)

    assert manager.get_session_id() != invalid_session_id


async def test_store_with_unexpected_chat_content_is_not_reused(hass, clock):
    invalid_session_id = str(uuid4())
    record = _valid_record(session_id=invalid_session_id)
    record["messages"] = [{"role": "user", "content": "private chat"}]
    await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_save(record)

    _, manager = await _setup_entry(hass)

    assert manager.get_session_id() != invalid_session_id


async def test_expired_persisted_record_is_not_restored(hass, clock):
    old_session_id = str(uuid4())
    old_activity = INITIAL_TIME - timedelta(hours=24)
    await Store(hass, SESSION_STORE_VERSION, SESSION_STORE_KEY).async_save(
        _valid_record(
            session_id=old_session_id,
            last_activity_at=old_activity.isoformat(),
        )
    )

    _, manager = await _setup_entry(hass)

    assert manager.get_session_id() != old_session_id


async def test_agent_stats_and_context_compression_do_not_change_session_id(
    hass, clock
):
    _, manager = await _setup_entry(hass)
    session_id = manager.get_session_id()
    await manager.async_confirm_session(session_id)

    # The manager consumes only accepted session IDs and time. AstrBot token
    # statistics and internal context compression are not session inputs.
    clock.advance(timedelta(hours=1))
    assert manager.get_session_id() == session_id

    record = await _stored_record(hass)
    assert set(record) == STORAGE_FIELDS

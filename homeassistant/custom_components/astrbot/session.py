"""Single-user AstrBot session identity and persistence."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    API_KEY_USERNAME_PREFIX,
    SESSION_DATA_VERSION,
    SESSION_TTL,
)


class AstrBotSessionManager:
    """Maintain the one active AstrBot session for this HA integration."""

    def __init__(
        self,
        store: Store[dict[str, Any]],
        base_url: str,
        api_key_id: str,
    ) -> None:
        """Initialize the manager for the configured AstrBot identity."""
        self._store = store
        self._base_url = base_url.rstrip("/")
        self._api_key_id = api_key_id
        self.username = f"{API_KEY_USERNAME_PREFIX}{api_key_id}"

        self._session_id: str | None = None
        self._created_at: datetime | None = None
        self._last_activity_at: datetime | None = None

    async def async_load(self) -> None:
        """Restore a valid, non-expired session from HA Store."""
        data = await self._store.async_load()
        record = self._validated_record(data)
        if record is None:
            return

        now = dt_util.utcnow()
        if now - record["last_activity_at"] >= SESSION_TTL:
            return

        self._session_id = record["session_id"]
        self._created_at = record["created_at"]
        self._last_activity_at = record["last_activity_at"]

    def get_session_id(self) -> str:
        """Return the active session ID, creating an in-memory candidate."""
        now = dt_util.utcnow()
        if self._session_id is None or (
            self._last_activity_at is not None
            and now - self._last_activity_at >= SESSION_TTL
        ):
            self._session_id = str(uuid4())
            self._created_at = now
            self._last_activity_at = None

        return self._session_id

    async def async_invalidate_session(self, session_id: str) -> None:
        """Drop a session mapping after AstrBot confirms an owner mismatch."""
        if session_id != self._session_id:
            raise ValueError("AstrBot session_id does not match the active session")

        await self._store.async_remove()
        self._session_id = None
        self._created_at = None
        self._last_activity_at = None

    async def async_confirm_session(self, session_id: str) -> None:
        """Persist activity only after AstrBot confirms this requested ID."""
        if session_id != self._session_id:
            raise ValueError("AstrBot session_id does not match the active request")

        now = dt_util.utcnow()
        created_at = self._created_at or now
        record = {
            "version": SESSION_DATA_VERSION,
            "base_url": self._base_url,
            "api_key_id": self._api_key_id,
            "username": self.username,
            "session_id": session_id,
            "created_at": created_at.isoformat(),
            "last_activity_at": now.isoformat(),
        }
        await self._store.async_save(record)

        self._created_at = created_at
        self._last_activity_at = now

    def _validated_record(self, data: Any) -> dict[str, str | datetime] | None:
        """Return a parsed record only when its schema and identity are valid."""
        if not isinstance(data, dict):
            return None

        if set(data) != {
            "version",
            "base_url",
            "api_key_id",
            "username",
            "session_id",
            "created_at",
            "last_activity_at",
        }:
            return None

        if (
            data.get("version") != SESSION_DATA_VERSION
            or data.get("base_url") != self._base_url
            or data.get("api_key_id") != self._api_key_id
            or data.get("username") != self.username
        ):
            return None

        session_id = data.get("session_id")
        if not isinstance(session_id, str):
            return None
        try:
            parsed_session_id = UUID(session_id)
        except ValueError:
            return None
        if parsed_session_id.version != 4:
            return None

        created_at = self._parse_timestamp(data.get("created_at"))
        last_activity_at = self._parse_timestamp(data.get("last_activity_at"))
        if (
            created_at is None
            or last_activity_at is None
            or last_activity_at < created_at
        ):
            return None

        return {
            "session_id": session_id,
            "created_at": created_at,
            "last_activity_at": last_activity_at,
        }

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        """Parse a timezone-aware ISO-8601 timestamp as UTC."""
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

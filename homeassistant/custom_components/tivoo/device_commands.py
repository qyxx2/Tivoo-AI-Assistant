"""Pure Tivoo SPP command payload builders.

Adapted from the pinned d03n3rfr1tz3/esp32-divoom and solar2ain/tivoo-control
implementations, cross-checked against d03n3rfr1tz3/hass-divoom Tivoo goldens.
This module returns command payloads only; protocol.py adds the outer frame.
"""

from collections.abc import Iterable
from datetime import datetime

from .rendering import parse_color

WEATHER_CODES = frozenset({1, 3, 5, 6, 8, 9})
AUDIO_SOURCES = {
    "bluetooth": 0x00,
    "fm": 0x01,
    "linein": 0x02,
    "sdcard": 0x03,
    "usb": 0x07,
}
GAME_CONTROLS = {
    "go": 0,
    "left": 1,
    "right": 2,
    "up": 3,
    "down": 4,
    "ok": 5,
}


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _frequency_bytes(frequency: object | None) -> tuple[int, int]:
    if frequency is None:
        return 0, 0
    value = round(float(frequency) * 10)
    if not 640 <= value <= 1080:
        raise ValueError("frequency must be between 64 and 108 MHz")
    if value > 1000:
        return value - 1000, value // 100
    return value % 100, value // 100


def _rgb(color: object | None) -> tuple[int, int, int] | None:
    if color is None:
        return None
    return parse_color(color)


def screen_power_payload(value: bool) -> bytes:
    if type(value) is not bool:
        raise TypeError("value must be a boolean")
    brightness = 100 if value else 0
    return bytes((0x45, 0x01, 0x01, 0x01, 0x01, brightness, 0x00, int(value), 0, 0, 0))


def playstate_payloads(value: str) -> tuple[bytes, ...]:
    if value == "previous":
        return (bytes((0x12, 0x00)),)
    if value == "next":
        return (bytes((0x12, 0x01)),)
    if value == "pause":
        return (bytes((0x0A, 0x00)),)
    if value == "play":
        return (bytes((0x0A, 0x01)),)
    raise ValueError("value must be previous, pause, play or next")


def clock_payloads(
    clock: int,
    *,
    twentyfour: bool = True,
    weather: bool = False,
    temp: bool = False,
    calendar: bool = False,
    color: object | None = None,
    hot: bool | None = None,
) -> tuple[bytes, ...]:
    clock = _integer(clock, "clock", 0, 6)
    if any(type(value) is not bool for value in (twentyfour, weather, temp, calendar)):
        raise TypeError("clock flags must be booleans")
    rgb = _rgb(color)
    view = bytearray((0x45, 0x00, int(twentyfour), clock, 0x01, int(weather), int(temp), int(calendar)))
    if rgb is not None:
        view.extend(rgb)
    payloads = [bytes((0x2D, int(twentyfour))), bytes(view)]
    if hot is not None:
        if type(hot) is not bool:
            raise TypeError("hot must be a boolean")
        payloads.append(bytes((0x26, int(hot))))
    return tuple(payloads)


def datetime_payload(value: str | None = None) -> bytes:
    clock = datetime.now() if value is None else datetime.fromisoformat(value)
    return bytes(
        (
            0x18,
            clock.year % 100,
            clock.year // 100,
            clock.month,
            clock.day,
            clock.hour,
            clock.minute,
            clock.second,
        )
    )


def weather_payloads(temperature: object, condition: int, unit: str = "C") -> tuple[bytes, ...]:
    condition = _integer(condition, "condition", 0, 255)
    if condition not in WEATHER_CODES:
        raise ValueError(f"unsupported weather condition code: {condition}")
    unit = str(unit).upper()
    temp = float(temperature)
    if unit == "F":
        temp = (temp - 32) * 5 / 9
        unit_code = 1
    elif unit == "C":
        unit_code = 0
    else:
        raise ValueError("unit must be C or F")
    celsius = round(temp)
    if not -128 <= celsius <= 127:
        raise ValueError("temperature is outside the supported range")
    return bytes((0x5F, celsius & 0xFF, condition)), bytes((0x2B, unit_code))


def light_payload(
    *,
    brightness: int,
    color: object | None = None,
    effect: int | None = None,
    power: bool = True,
) -> bytes:
    brightness = _integer(brightness, "brightness", 0, 100)
    if type(power) is not bool:
        raise TypeError("power must be a boolean")
    rgb = _rgb(color)
    if rgb is None:
        rgb = (255, 255, 255)
        if effect is None:
            effect = 1
    elif effect is None:
        effect = 0
    effect = _integer(effect, "effect", 0, 4)
    return bytes((0x45, 0x01, *rgb, brightness, effect, int(power), 0, 0, 0))


def lyrics_payload() -> bytes:
    return bytes((0x45, 0x06, 0x00, 0x00, 0x00))


def scoreboard_payload(player1: int = 0, player2: int = 0) -> bytes:
    player1 = _integer(player1, "player1", 0, 65535)
    player2 = _integer(player2, "player2", 0, 65535)
    return bytes((0x72, 0x01, 0x01)) + player2.to_bytes(2, "little") + player1.to_bytes(2, "little")


def timer_payload(value: bool) -> bytes:
    if type(value) is not bool:
        raise TypeError("value must be a boolean")
    return bytes((0x72, 0x00, int(value)))


def noise_payload(value: bool) -> bytes:
    if type(value) is not bool:
        raise TypeError("value must be a boolean")
    return bytes((0x72, 0x02, 0x01 if value else 0x02))


def alarm_payload(
    *,
    slot: int = 0,
    time: str | None = None,
    weekdays: Iterable[str] | None = None,
    frequency: object | None = None,
    volume: int = 100,
) -> bytes:
    slot = _integer(slot, "slot", 0, 255)
    volume = _integer(volume, "volume", 0, 100)
    if time is None:
        enabled, hour, minute = 0, 0, 0
    else:
        parsed = datetime.strptime(time, "%H:%M")
        enabled, hour, minute = 1, parsed.hour, parsed.minute
    day_bits = {"sun": 1, "mon": 2, "tue": 4, "wed": 8, "thu": 16, "fri": 32, "sat": 64}
    weekbits = 0
    if weekdays is not None:
        for day in weekdays:
            try:
                weekbits |= day_bits[day]
            except KeyError as exc:
                raise ValueError(f"unsupported weekday: {day}") from exc
    lo, hi = _frequency_bytes(frequency)
    return bytes((0x43, slot, enabled, hour, minute, weekbits, 0, 0, lo, hi, volume))


def memorial_payload(
    *,
    slot: int = 0,
    value: str | None = None,
    text: str = "Home Assistant",
) -> bytes:
    slot = _integer(slot, "slot", 0, 255)
    if value is None:
        enabled, month, day, hour, minute = 0, 0, 0, 0, 0
    else:
        clock = datetime.fromisoformat(value)
        enabled, month, day, hour, minute = 1, clock.month, clock.day, clock.hour, clock.minute
    encoded = str(text).encode("utf-16-be")
    if len(encoded) > 32:
        raise ValueError("memorial text must fit within 16 UTF-16 code units")
    encoded = encoded.ljust(32, b"\x00")
    return bytes((0x54, slot, enabled, month, day, hour, minute, 0x01)) + encoded


def audio_source_payloads(value: str, frequency: object | None = None) -> tuple[bytes, ...]:
    try:
        source = AUDIO_SOURCES[value]
    except KeyError as exc:
        raise ValueError(f"unsupported audio source: {value}") from exc
    payloads = [bytes((0x05, source))]
    if value == "fm" and frequency is not None:
        lo, hi = _frequency_bytes(frequency)
        payloads.append(bytes((0x61, lo, hi)))
    return tuple(payloads)


def sleep_payload(
    *,
    value: bool,
    time: int = 120,
    mode: int = 0,
    frequency: object | None = None,
    volume: int = 100,
    color: object = "black",
    brightness: int = 100,
) -> bytes:
    if type(value) is not bool:
        raise TypeError("value must be a boolean")
    time = _integer(time, "time", 0, 255)
    mode = _integer(mode, "mode", 0, 255)
    volume = _integer(volume, "volume", 0, 100)
    brightness = _integer(brightness, "brightness", 0, 100)
    rgb = _rgb(color)
    assert rgb is not None
    lo, hi = _frequency_bytes(frequency)
    return bytes((0x40, time, mode, int(value), lo, hi, volume, *rgb, brightness))


def design_payloads(number: int) -> tuple[bytes, ...]:
    number = _integer(number, "number", 0, 3)
    return bytes((0x45, 0x05)), bytes((0xBD, 0x17, number))


def effects_payload(number: int) -> bytes:
    return bytes((0x45, 0x03, _integer(number, "number", 0, 255)))


def visualization_payload(number: int) -> bytes:
    return bytes((0x45, 0x04, _integer(number, "number", 0, 255)))


def game_payload(index: int | None = None) -> bytes:
    if index is None:
        return bytes((0xA0, 0x00, 0x00))
    return bytes((0xA0, 0x01, _integer(index, "index", 0, 127)))


def game_control_payloads(value: str) -> tuple[bytes, ...]:
    try:
        action = GAME_CONTROLS[value]
    except KeyError as exc:
        raise ValueError(f"unsupported game control: {value}") from exc
    if action == 0:
        return (bytes((0x88,)),)
    return bytes((0x17, action)), bytes((0x21, action))

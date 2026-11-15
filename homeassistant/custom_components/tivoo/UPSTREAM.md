# Reused Tivoo display assets

The built-in pixel-art presets, emotion preset factories, scrolling text frame
renderer, color parsing behavior, Unifont font, and pure image/GIF frame
conversion behavior are adapted from the Tivoo SDK source set, with its
upstream origin and pinned revision recorded below.

Upstream project: https://github.com/solar2ain/tivoo-control
Pinned upstream commit: 6f24deaf631820089259177805d1a6a6615f6d7e
The upstream README declares MIT. The source repository has no separate
LICENSE file; see the P4b0 preflight report for the exact provenance decision.

The integration reuses only pure preset/render/font/media behavior from this SDK.
The media conversion follows its `image_file_to_pixels()` and GIF frame loop:
resize RGBA frames to 16×16 with Lanczos, then map alpha values below 32 to
black. Home Assistant media processing keeps the GIF's embedded per-frame
milliseconds unless an explicit frame-time override is supplied.

The Android Bluetooth Bridge client, RFCOMM/SPP transport, CLI, device identity,
and external-workspace runtime imports are intentionally excluded. Retain this
attribution and upstream notices with the adapted files.


## Raw Tivoo protocol encoding

The P5b3 `protocol.py` encoder also adapts the pure display-protocol portions of the same pinned Tivoo SDK source set:

- `tivoo/tivoo.py::_build_packet()`: outer Tivoo length/checksum/frame wrapper.
- `tivoo/tivoo.py::encode_image()` and `build_image_frame()`: 16×16 RGB palette and packed pixel encoding.
- `tivoo/tivoo.py::_send_animation()`: 200-byte `0x49` animation chunk format.
- `tivoo/commands.py::volume_payload()` and `countdown_payload()`: audio volume and countdown payload values.

Only the pure Python byte/pixel encoding behavior is adapted. The CLI, Android Bluetooth Bridge, RFCOMM/SPP client, and device connection lifecycle are not imported into Home Assistant. The ESP32 receives complete frames from HA and forwards them unchanged; it does not encode pixels or reimplement payload generation.

## 2026-11-14 Tivoo SPP capability expansion

The Assist/MCP surface was expanded after the original seven-tool P4 MVP by
cross-checking the Tivoo-specific implementations and golden vectors in:

- d03n3rfr1tz3/esp32-divoom commit e90a77bbade7e92523bfb5b69bc5cb1e4d167520.
- d03n3rfr1tz3/hass-divoom main commit 0e9959a9009d9f8ce3be79476f464d593d85bc91;
  especially custom_components/divoom/devices/tivoo.py, devices/divoom.py,
  and tests/goldens/Tivoo/.
- solar2ain/tivoo-control commit 6f24deaf631820089259177805d1a6a6615f6d7e.

device_commands.py contains only pure Tivoo/Divoom payload construction.
Runtime Bluetooth/RFCOMM remains on the ESP32 bridge. The added service/tool
surface covers screen power, brightness, playback, clock/date-time/weather,
light mode, Tivoo lyrics and scoreboard, timer/noise meter, alarm/memorial,
audio source, sleep mode, design/effects/visualization, game/game control,
plus the original volume/countdown/text/image/animation/presets.

The Tivoo-specific hass-divoom driver explicitly rejects equalizer and
keyboard-light control; those are not exposed. Raw arbitrary packets are also
not exposed to MCP. Effects, visualization and game indices are protocol-valid
but device/App-version dependent, so their tool descriptions do not invent
semantic index names. The existing ESP32 DEVICE_STATUS/DEVICE_EVENT snapshot
is transport/device-health state; opaque Tivoo SPP reverse bytes are not
reclassified as a complete business-state API.

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

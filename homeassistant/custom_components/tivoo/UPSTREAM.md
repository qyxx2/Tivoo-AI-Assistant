# Reused Tivoo display assets

The built-in pixel-art presets, emotion preset factories, scrolling text frame
renderer, color parsing behavior, and Unifont font are adapted from the
Tivoo SDK source set, with its upstream origin and pinned revision recorded
below.

Upstream project: https://github.com/solar2ain/tivoo-control
Pinned upstream commit: 6f24deaf631820089259177805d1a6a6615f6d7e
The upstream README declares MIT. The source repository has no separate
LICENSE file; see the P4b0 preflight report for the exact provenance decision.

Only the pure preset/render/font assets needed by this integration are bundled.
The Android Bluetooth Bridge client, RFCOMM/SPP transport, CLI, device identity,
and external-workspace runtime imports are intentionally excluded.
Retain this attribution and upstream notices with the copied files.

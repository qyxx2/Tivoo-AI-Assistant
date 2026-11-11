# Tivoo ESP32 firmware (P5b1)

This is the production ESP-IDF project for the ESP32-WROVER-E-N16R8 target. It is pinned to ESP-IDF v6.1 and `IDF_TARGET=esp32`. The dependency lock and partition layout are carried forward from the P5b0 compatibility verification.

## Local build

From this directory on the ARM64 Ubuntu development machine:

```bash
. /home/Gold/.espressif/tools/activate_idf_v6.1.sh
idf.py set-target esp32
idf.py menuconfig
idf.py build
```

In menuconfig, open **Tivoo Wi-Fi** and set `TIVOO_WIFI_SSID` and `TIVOO_WIFI_PASSWORD` for the local 2.4 GHz network. IDF stores these values in the ignored local `sdkconfig`; keep that file out of commits and never paste credentials into source files, defaults, issue logs, or build reports.

The generated application image is `build/tivoo_firmware.bin`.

## P5b1 network lifecycle

The firmware starts the Wi-Fi Station and the two TCP listener tasks. Neither listener opens a socket before Station receives an IPv4 address. After `IP_EVENT_STA_GOT_IP`, it listens on IPv4 `INADDR_ANY` at:

- TCP 7777 — control channel placeholder
- TCP 7778 — diagnostic channel placeholder

Each port accepts one active client. A second client is closed. Station disconnect / IPv4 loss closes both accepted clients and listener sockets; a later IPv4 event enables them again.

This batch implements connection lifecycle only. It intentionally does not parse command frames, implement the 7778 HELLO/message protocol, forward Bluetooth SPP commands, or implement audio. Those remain in their already-defined later P5 batches.

## Host network simulator

The test compiles the same `network_listeners.c` source with GCC and a pthread-backed host shim. From the repository root:

```bash
PYTHONPATH=homeassistant .venv/bin/python - <<'PY'
import homeassistant
import pytest
raise SystemExit(pytest.main(["tests/esp32/test_p5b1_network_listeners.py", "-q"]))
PY
```

The simulator covers listeners initially offline, both ports opening after an IP-up event, the one-client limit per port, closing accepted clients/listeners on IP-down, and reopening on a subsequent IP-up event.

No development-board flashing is part of P5b1.

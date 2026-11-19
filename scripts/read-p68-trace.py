#!/usr/bin/env python3
"""Decode a one-shot P68TRACE console capture. No cache alignment assumed."""
import argparse
import json
import struct
from pathlib import Path

HEADER = struct.Struct("<QQQIIII")


def records(blob):
    offset = 0
    while offset < len(blob):
        if len(blob) - offset < HEADER.size:
            raise ValueError("truncated header")
        index, epoch, aux, kind, flags, count, extra = HEADER.unpack_from(blob, offset)
        offset += HEADER.size
        result = dict(index=index, epoch=epoch, aux=aux, kind=kind, flags=flags,
                      count=count, extra=extra)
        if kind not in (1, 2, 3, 4, 5) or (kind >= 3 and (count or extra)):
            raise ValueError("invalid record")
        size = count * (8 if kind == 1 else 2) + extra * 2
        if size > len(blob) - offset:
            raise ValueError("truncated payload")
        if kind == 1:
            slots = struct.unpack_from(f"<{count*2}i", blob, offset)
            result.update(left=slots[::2], right=slots[1::2],
                          tx=struct.unpack_from(f"<{extra}h", blob, offset+count*8))
        elif kind == 2:
            result.update(pcm=struct.unpack_from(f"<{count}h", blob, offset),
                          cache=struct.unpack_from(f"<{extra}h", blob, offset+count*2))
        offset += size
        yield result


def read_serial(lines):
    streams, complete = {}, {}
    for line in lines:
        if not line.startswith("P68TRACE "):
            continue
        fields = line.split()
        action = fields[1]
        if action not in ("BEGIN", "DATA", "END"):
            continue
        name = fields[2]
        if action == "BEGIN":
            if name in streams or name in complete:
                raise ValueError(f"duplicate stream {name}")
            streams[name] = (bytearray(), int(fields[3]), int(fields[4]))
        elif action == "DATA":
            buf, dropped, size = streams[name]
            if int(fields[3]) != len(buf):
                raise ValueError(f"missing/out-of-order chunk in {name}")
            buf.extend(bytes.fromhex(fields[4]))
            if len(buf) > size:
                raise ValueError(f"extra data in {name}")
        else:
            buf, dropped, size = streams.pop(name)
            if len(buf) != size:
                raise ValueError(f"truncated stream {name}")
            complete[name] = (bytes(buf), dropped)
    if streams or not complete:
        raise ValueError("incomplete trace")
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial_log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    streams = read_serial(args.serial_log.read_text(errors="replace").splitlines())
    if set(streams) != {"raw", "afe"}:
        raise ValueError("both raw and afe streams required")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, (blob, dropped) in streams.items():
        (args.output / f"{name}.bin").write_bytes(blob)
        with (args.output / f"{name}.jsonl").open("w") as out:
            for record in records(blob):
                out.write(json.dumps(record) + "\n")
        print(f"{name}: {len(blob)} bytes, {dropped} dropped records")


if __name__ == "__main__":
    main()

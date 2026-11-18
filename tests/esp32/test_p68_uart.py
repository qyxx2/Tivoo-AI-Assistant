"""Host golden vectors for the exact firmware UART codec."""
import ctypes as C
import pathlib
import struct
import subprocess
import zlib
import pytest

MAIN = pathlib.Path(__file__).resolve().parents[2] / "esp32/firmware/main"

@pytest.fixture(scope="module")
def codec(tmp_path_factory):
    lib = tmp_path_factory.mktemp("uart") / "wire.so"
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared",
                    "-fPIC", str(MAIN / "uart_wire.c"), "-o", str(lib)], check=True)
    dll = C.CDLL(str(lib))
    dll.uart_wire_encode.argtypes = [C.c_uint8, C.c_uint64, C.c_uint32,
                                    C.c_uint32, C.c_void_p, C.c_uint16, C.c_void_p]
    dll.uart_wire_encode.restype = C.c_size_t
    dll.uart_wire_decode.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p]
    dll.uart_wire_decode.restype = C.c_bool
    return dll

def uncobs(data):
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        assert code and i + code <= len(data)
        out += data[i+1:i+code]
        i += code
        if code != 255 and i < len(data):
            out.append(0)
    return bytes(out)

def cobs(data):
    out = bytearray(b"\0")
    index = 0
    code = 1
    for b in data:
        if b == 0:
            out[index] = code
            index = len(out)
            out.append(0)
            code = 1
        else:
            out.append(b)
            code += 1
            if code == 255:
                out[index] = code
                index = len(out)
                out.append(0)
                code = 1
    out[index] = code
    return bytes(out)

@pytest.mark.parametrize("kind,seq,epoch,data", [
    (1,0,0,b""), (4,0,0,b"\x02\x01\x11\x22\x33\x44\x55\x66"),
    (0x12,1,2,b"\x69\x00\x01\x02\x03\x04\x05"),
    (0x13,2,2,bytes(range(256))*18), (0x14,1,2,b"\0\x69\x96"),
    (0x15,1,2,b"\0"), (0x10,1,2,b"")])
def test_wire_golden(codec, kind, seq, epoch, data):
    token = 0x123456789abcdef0
    raw = struct.pack("<BBHQII",1,kind,len(data),token,seq,epoch)+data
    raw += struct.pack("<I",zlib.crc32(raw))
    out = C.create_string_buffer(4652)
    n = codec.uart_wire_encode(kind,token,seq,epoch,data,len(data),out)
    assert 1 <= n <= 4652
    assert out.raw[n-1] == 0
    assert uncobs(out.raw[:n-1]) == raw
    decoded = C.create_string_buffer(4700)
    assert codec.uart_wire_decode(out,n-1,decoded)
    assert not codec.uart_wire_decode(out,n-2,decoded)
    damaged = bytearray(raw)
    damaged[-1] ^= 1
    bad = cobs(damaged)
    assert not codec.uart_wire_decode(bad,len(bad),decoded)

@pytest.mark.parametrize("kind,seq,epoch,data", [
    (99,0,0,b""),(1,1,0,b""),(0x12,0,1,b"\x69"+b"\0"*6),
    (0x10,1,0,b""),(0x15,1,1,b"\x02"),(4,0,0,b"\x02"+b"\0"*7),
    (0x12,1,1,b"\x00"*7),(0x14,1,1,b"")])
def test_invalid_fields(codec,kind,seq,epoch,data):
    raw = struct.pack("<BBHQII",1,kind,len(data),1,seq,epoch)+data
    raw += struct.pack("<I",zlib.crc32(raw))
    encoded = cobs(raw)
    assert not codec.uart_wire_decode(encoded,len(encoded),C.create_string_buffer(4700))

def test_stream_and_link(tmp_path):
    binary = tmp_path / "link"
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(MAIN / "uart_wire.c"),
                    str(MAIN / "uart_link.c"),
                    str(MAIN.parents[1] / "tests/p68_uart/link_host.c"),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)

def test_router_and_reverse_capacity(tmp_path):
    binary = tmp_path / "router"
    subprocess.run(["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(MAIN), str(MAIN / "uart_router.c"),
                    str(MAIN / "tivoo_frame_stream.c"),
                    str(MAIN.parents[1] / "tests/p68_uart/router_host.c"),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)

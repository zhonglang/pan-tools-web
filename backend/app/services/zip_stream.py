import struct
import zlib
from collections.abc import Iterator


def stream_stored_zip(
    files: list[tuple[str, int, Iterator[bytes] | None]],
) -> Iterator[bytes]:
    central: list[tuple[bytes, int, int, int]] = []
    offset = 0
    for name, size, chunks in files:
        name_bytes = name.encode("utf-8")
        local = _local_header(name_bytes)
        yield local
        crc = 0
        written = 0
        if chunks is not None:
            for chunk in chunks:
                if not chunk:
                    continue
                crc = zlib.crc32(chunk, crc)
                written += len(chunk)
                yield chunk
        if written != size:
            raise ValueError("压缩包条目大小不一致")
        descriptor = struct.pack(
            "<IIQQ", 0x08074B50, crc & 0xFFFFFFFF, written, written
        )
        yield descriptor
        central.append((name_bytes, crc & 0xFFFFFFFF, written, offset))
        offset += len(local) + written + len(descriptor)

    central_start = offset
    parts: list[bytes] = []
    for name_bytes, crc, written, local_offset in central:
        extra = struct.pack("<HHQQQ", 0x0001, 24, written, written, local_offset)
        header = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            45,
            45,
            0x0808,
            0,
            0,
            0,
            crc,
            0xFFFFFFFF,
            0xFFFFFFFF,
            len(name_bytes),
            len(extra),
            0,
            0,
            0,
            0,
            0xFFFFFFFF,
        )
        parts.append(header + name_bytes + extra)
    central_blob = b"".join(parts)
    yield central_blob
    yield struct.pack(
        "<IQHHIIQQQQ",
        0x06064B50,
        44,
        45,
        45,
        0,
        0,
        len(central),
        len(central),
        len(central_blob),
        central_start,
    )
    yield struct.pack("<IIQI", 0x07064B50, 0, central_start + len(central_blob), 1)
    yield struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )


def stored_zip_size(files: list[tuple[str, int]]) -> int:
    total = 0
    for name, size in files:
        name_len = len(name.encode("utf-8"))
        total += 30 + name_len + size + 24
        total += 46 + name_len + 28
    total += 56 + 20 + 22
    return total


def _local_header(name_bytes: bytes) -> bytes:
    return (
        struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            45,
            0x0808,
            0,
            0,
            0,
            0,
            0xFFFFFFFF,
            0xFFFFFFFF,
            len(name_bytes),
            0,
        )
        + name_bytes
    )

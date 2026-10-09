import io
import zipfile

from app.services.zip_stream import stored_zip_size, stream_stored_zip


def test_stored_zip_round_trip():
    files = [
        ("相册/说明.txt", 5, iter([b"he", b"llo"])),
        ("相册/空目录/", 0, None),
    ]
    blob = b"".join(stream_stored_zip(files))
    assert len(blob) == stored_zip_size([("相册/说明.txt", 5), ("相册/空目录/", 0)])
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.read("相册/说明.txt") == b"hello"
        assert archive.getinfo("相册/空目录/").is_dir()

from app.services.local_folder import DownloadCancelled, write_entries


def test_write_reports_bytes_while_a_large_file_is_still_open(tmp_path):
    class Adapter:
        def open_download(self, cookie, path):
            yield b"aa"
            yield b"bbbb"

    seen: list[tuple[int, int, str]] = []
    directory = write_entries(
        Adapter(),
        "cookie",
        "/毕业照",
        tmp_path,
        [("毕业照/视频.mp4", "/毕业照/视频.mp4", 6)],
        lambda written, files_done, name: seen.append((written, files_done, name)),
        lambda: False,
    )
    assert seen == [(2, 0, "视频.mp4"), (6, 0, "视频.mp4"), (6, 1, "视频.mp4")]
    assert (tmp_path / "毕业照" / "视频.mp4").read_bytes() == b"aabbbb"
    assert directory == str((tmp_path / "毕业照").resolve())


def test_write_stops_before_the_next_chunk(tmp_path):
    class Adapter:
        def open_download(self, cookie, path):
            yield b"aa"
            yield b"bbbb"

    written = {"n": 0}

    def progress(done, files_done, name):
        written["n"] = done

    try:
        write_entries(
            Adapter(),
            "cookie",
            "/毕业照",
            tmp_path,
            [("毕业照/视频.mp4", "/毕业照/视频.mp4", 6)],
            progress,
            lambda: written["n"] > 0,
        )
    except DownloadCancelled:
        pass
    else:
        raise AssertionError("expected cancel")
    assert (tmp_path / "毕业照" / "视频.mp4").read_bytes() == b"aa"

from collections.abc import Iterator

from app.pans.baidu import BaiduAdapter
from app.pans.errors import TransferFailed

MAX_ARCHIVE_FILES = 10000


class FolderTooLarge(Exception):
    pass


def archive_entries(adapter: BaiduAdapter, cookie: str, directory: str) -> list[tuple[str, str | None, int]]:
    base = "全部文件" if directory == "/" else directory.rstrip("/").rsplit("/", 1)[-1]
    planned: list[tuple[str, str | None, int]] = []

    def display(parts: list[str], is_dir: bool) -> str:
        name = "/".join([base, *parts]) if parts else base
        if is_dir and not name.endswith("/"):
            name += "/"
        return name

    def walk(path: str, parts: list[str]) -> None:
        entries = adapter.list_dir(cookie, path)
        if not entries:
            planned.append((display(parts, True), None, 0))
            return
        folders: list[tuple[str, list[str]]] = []
        for entry in entries:
            if len(planned) >= MAX_ARCHIVE_FILES:
                raise FolderTooLarge()
            child = parts + [entry.name]
            if entry.is_dir:
                folders.append((entry.path, child))
                continue
            if entry.size is None:
                raise TransferFailed()
            planned.append((display(child, False), entry.path, entry.size))
        for folder, child in folders:
            walk(folder, child)

    walk(directory, [])
    return planned


def archive_body(adapter: BaiduAdapter, cookie: str, planned: list[tuple[str, str | None, int]]) -> Iterator[bytes]:
    from app.services.zip_stream import stream_stored_zip

    files: list[tuple[str, int, Iterator[bytes] | None]] = []
    for name, path, size in planned:
        if path is None:
            files.append((name, 0, None))
            continue

        def chunks(remote: str = path) -> Iterator[bytes]:
            yield from adapter.open_download(cookie, remote)

        files.append((name, size, chunks()))
    yield from stream_stored_zip(files)

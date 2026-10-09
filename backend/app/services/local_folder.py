import os
from collections.abc import Callable
from pathlib import Path

from app.pans.baidu import BaiduAdapter
from app.pans.errors import TransferFailed


class DownloadCancelled(Exception):
    pass


def download_root() -> Path:
    raw = os.environ.get("PAN_DOWNLOAD_DIR")
    root = Path(raw).expanduser() if raw else Path.home() / "Downloads"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def write_entries(
    adapter: BaiduAdapter,
    cookie: str,
    directory: str,
    root: Path,
    planned: list[tuple[str, str | None, int]],
    progress: Callable[[int, int, str], None],
    stop: Callable[[], bool],
) -> str:
    base = directory.rstrip("/").rsplit("/", 1)[-1]
    dest = _inside(root, root / _segment(base))
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    files_done = 0
    prefix = f"{base}/"
    for name, remote, _size in planned:
        if stop():
            raise DownloadCancelled()
        relative = name[len(prefix):] if name.startswith(prefix) else ""
        parts = [_segment(part) for part in relative.split("/") if part not in {"", ".", ".."}]
        if remote is None:
            folder = dest
            for part in parts:
                folder = _inside(dest, folder / part)
                folder.mkdir(parents=True, exist_ok=True)
            continue
        if not parts:
            raise TransferFailed()
        folder = dest
        for part in parts[:-1]:
            folder = _inside(dest, folder / part)
            folder.mkdir(parents=True, exist_ok=True)
        file_path = _inside(dest, folder / parts[-1])
        current = parts[-1]
        with file_path.open("wb") as handle:
            for chunk in adapter.open_download(cookie, remote):
                if stop():
                    raise DownloadCancelled()
                handle.write(chunk)
                written += len(chunk)
                progress(written, files_done, current)
        files_done += 1
        progress(written, files_done, current)
    return str(dest)


def _segment(name: str) -> str:
    cleaned = name.replace("/", "／").replace("\\", "／").replace("\x00", "").strip()
    if cleaned in {"", ".", ".."}:
        return "未命名"
    return cleaned[:180]


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise TransferFailed()
    return resolved

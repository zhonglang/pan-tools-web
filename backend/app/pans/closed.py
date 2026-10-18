from app.pans.errors import ProviderClosed, TransferFailed


class ClosedAdapter:
    def verify_login(self, cookie: str) -> str:
        raise ProviderClosed()

    def ensure_dir(self, cookie: str, path: str) -> None:
        raise ProviderClosed()

    def ensure_subdir(self, cookie: str, dest: str, relative_dir: str) -> str:
        raise ProviderClosed()

    def upload_file(
        self,
        cookie: str,
        dest_dir: str,
        filename: str,
        stream,
        size: int,
        *,
        on_progress=None,
        should_stop=None,
    ) -> None:
        raise TransferFailed("不支持")

from app.pans.errors import ProviderClosed


class ClosedAdapter:
    def verify_login(self, cookie: str) -> str:
        raise ProviderClosed()

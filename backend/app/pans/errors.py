class LoginRejected(Exception):
    pass


class ProviderClosed(Exception):
    def __init__(self) -> None:
        super().__init__("暂未开放")

class LoginRejected(Exception):
    pass


class ProviderClosed(Exception):
    def __init__(self) -> None:
        super().__init__("暂未开放")


class PathNotFound(Exception):
    pass


class WrongPassword(Exception):
    pass


class InvalidLink(Exception):
    pass


class DuplicateName(Exception):
    pass


class RateLimited(Exception):
    pass


class TransferFailed(Exception):
    pass


class NotAFile(Exception):
    pass


class UploadCancelled(Exception):
    pass

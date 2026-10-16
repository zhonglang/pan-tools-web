import httpx

from app.pans.baidu import BaiduAdapter
from app.pans.closed import ClosedAdapter
from app.pans.errors import LoginRejected, ProviderClosed

__all__ = ["LoginRejected", "ProviderClosed", "adapter_for"]


def adapter_for(provider: str, client: httpx.Client):
    if provider == "baidu":
        return BaiduAdapter(client)
    if provider == "quark":
        from app.pans.quark import QuarkAdapter

        return QuarkAdapter(client)
    if provider == "xunlei":
        from app.pans.xunlei import XunleiAdapter

        return XunleiAdapter(client)
    raise ValueError("网盘类型无效")

import re
from dataclasses import dataclass

_SHARE = re.compile(r"https?://pan\.baidu\.com/s/1([0-9A-Za-z_-]+)")
_PWD_QUERY = re.compile(r"[?&]pwd=([0-9A-Za-z]{4})")
_PWD_LABEL = re.compile(r"提取码\s*[:：]\s*([0-9A-Za-z]{4})")
_PWD_TAIL = re.compile(r"\s+([0-9A-Za-z]{4})\s*$")


@dataclass(frozen=True)
class ParsedLink:
    surl: str
    password: str | None


def parse_share_link(text: str) -> ParsedLink | None:
    matched = _SHARE.search(text.strip())
    if matched is None:
        return None
    password = None
    for pattern in (_PWD_QUERY, _PWD_LABEL, _PWD_TAIL):
        found = pattern.search(text)
        if found is not None:
            password = found.group(1)
            break
    return ParsedLink(surl=matched.group(1), password=password)


def split_link_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]

import re
from dataclasses import dataclass

_SHARE = re.compile(r"https?://pan\.baidu\.com/s/1([0-9A-Za-z_-]+)")
_QUARK = re.compile(r"https?://pan\.quark\.cn/s/([0-9A-Za-z]+)")
_XUNLEI = re.compile(r"https?://pan\.xunlei\.com/s/([0-9A-Za-z_-]+)")
_URL = re.compile(
    r"https?://(?:pan\.baidu\.com/s/1[0-9A-Za-z_-]+|pan\.quark\.cn/s/[0-9A-Za-z]+|pan\.xunlei\.com/s/[0-9A-Za-z_-]+)(?:\?[^\s\u00a0]*)?"
)
_PWD_QUERY = re.compile(r"[?&]pwd=([0-9A-Za-z]{4})")
_PWD_LABEL = re.compile(r"提取码\s*[:：]\s*([0-9A-Za-z]{4})")
_PWD_TAIL = re.compile(r"\s+([0-9A-Za-z]{4})\s*$")
_CAPTION = re.compile(r"通过百度网盘分享|通过夸克网盘|我用夸克网盘|超级会员")
_FOOTER = re.compile(
    r"复制这段内容|即可获取|点击链接或复制整段内容|提取码\s*[:：]\s*[0-9A-Za-z]{4}"
)
_TITLE = re.compile(r"分享的文件\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
_QUARK_TITLE = re.compile(r"分享了「([^」]+)」")


@dataclass(frozen=True)
class ParsedLink:
    surl: str
    password: str | None
    provider: str = "baidu"
    title: str | None = None


def _password(text: str) -> str | None:
    for pattern in (_PWD_QUERY, _PWD_LABEL):
        found = pattern.search(text)
        if found is not None:
            return found.group(1)
    for line in text.splitlines():
        if (
            _SHARE.search(line) is None
            and _QUARK.search(line) is None
            and _XUNLEI.search(line) is None
        ):
            continue
        tail = _PWD_TAIL.search(line)
        if tail is not None:
            return tail.group(1)
    return None


def _title(text: str) -> str | None:
    titled = _TITLE.search(text)
    if titled is not None:
        return titled.group(1).strip() or None
    quoted = _QUARK_TITLE.search(text)
    if quoted is not None:
        return quoted.group(1).strip() or None
    return None


def parse_share_link(text: str) -> ParsedLink | None:
    cleaned = text.strip()
    matched = _SHARE.search(cleaned)
    if matched is not None:
        return ParsedLink(
            surl=matched.group(1),
            password=_password(cleaned),
            provider="baidu",
            title=_title(cleaned),
        )
    quark = _QUARK.search(cleaned)
    if quark is not None:
        return ParsedLink(
            surl=quark.group(1),
            password=_password(cleaned),
            provider="quark",
            title=_title(cleaned),
        )
    xunlei = _XUNLEI.search(cleaned)
    if xunlei is not None:
        return ParsedLink(
            surl=xunlei.group(1),
            password=_password(cleaned),
            provider="xunlei",
            title=_title(cleaned),
        )
    return None


def share_chunks(text: str) -> list[str]:
    lines = text.splitlines()
    consumed: set[int] = set()
    chunks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line.strip() or _URL.search(line) is None:
            continue
        before: list[str] = []
        cursor = index - 1
        while (
            cursor >= 0
            and lines[cursor].strip()
            and cursor not in consumed
            and _URL.search(lines[cursor]) is None
        ):
            if _CAPTION.search(lines[cursor]) is None:
                break
            before.append(lines[cursor].strip())
            consumed.add(cursor)
            cursor -= 1
        before.reverse()
        after: list[str] = []
        cursor = index + 1
        while (
            cursor < len(lines)
            and lines[cursor].strip()
            and _URL.search(lines[cursor]) is None
        ):
            if _FOOTER.search(lines[cursor]) is None:
                break
            after.append(lines[cursor].strip())
            consumed.add(cursor)
            cursor += 1
        consumed.add(index)
        chunks.append((index, "\n".join([*before, line.strip(), *after]).strip()))
    chunks.sort(key=lambda item: item[0])
    unique: list[str] = []
    seen: set[str] = set()
    for _, chunk in chunks:
        parsed = parse_share_link(chunk)
        if parsed is None or parsed.surl in seen:
            continue
        seen.add(parsed.surl)
        unique.append(chunk)
    return unique


def canonical_input(chunk: str) -> str:
    parsed = parse_share_link(chunk)
    if parsed is None:
        return chunk.strip()
    if parsed.provider == "baidu":
        url = f"https://pan.baidu.com/s/1{parsed.surl}"
    elif parsed.provider == "xunlei":
        url = f"https://pan.xunlei.com/s/{parsed.surl}"
    else:
        url = f"https://pan.quark.cn/s/{parsed.surl}"
    if parsed.password:
        url += f"?pwd={parsed.password}"
    return url


def with_share_password(url: str, password: str | None) -> str:
    cleaned = (url or "").strip()
    code = (password or "").strip()
    if not cleaned or not code:
        return cleaned
    if "pwd=" in cleaned:
        return cleaned
    joiner = "&" if "?" in cleaned else "?"
    return f"{cleaned}{joiner}pwd={code}"


def split_link_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]

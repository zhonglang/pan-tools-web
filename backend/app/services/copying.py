MAX_TARGETS = 50
MAX_RENAME_ATTEMPTS = 50


def parent_of(path: str) -> str:
    cleaned = path.strip().rstrip("/") or "/"
    if cleaned == "/":
        return "/"
    parent = cleaned.rsplit("/", 1)[0]
    return parent or "/"


def same_parent(paths: list[str]) -> bool:
    if not paths:
        return False
    parents = {parent_of(path) for path in paths}
    return len(parents) == 1


def is_self_or_descendant(source: str, target: str) -> bool:
    src = source.strip().rstrip("/") or "/"
    tgt = target.strip().rstrip("/") or "/"
    if src == "/":
        return False
    return tgt == src or tgt.startswith(src + "/")


def next_copy_name(name: str, *, is_dir: bool, attempt: int) -> str:
    if attempt <= 0:
        return name
    if is_dir:
        return f"{name}({attempt})"
    dot = name.rfind(".")
    if dot <= 0:
        return f"{name}({attempt})"
    return f"{name[:dot]}({attempt}){name[dot:]}"


def validate_targets(source: str, targets: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in targets:
        path = raw.strip().rstrip("/") or "/"
        if path == "/":
            raise ValueError("目标目录无效")
        cleaned.append(path)
    if not cleaned or len(cleaned) > MAX_TARGETS:
        raise ValueError("目标目录数量无效")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("目标目录重复")
    if not same_parent(cleaned):
        raise ValueError("目标目录必须同级")
    src = source.strip().rstrip("/") or "/"
    for path in cleaned:
        if is_self_or_descendant(src, path):
            raise ValueError("不能复制到自身或子目录")
    return cleaned

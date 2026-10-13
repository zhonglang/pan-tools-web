import pytest

from app.services.copying import is_self_or_descendant, next_copy_name, parent_of, same_parent, validate_targets


def test_parent_of_and_same_parent():
    assert parent_of("/") == "/"
    assert parent_of("/a") == "/"
    assert parent_of("/a/b") == "/a"
    assert same_parent(["/父/A", "/父/B"]) is True
    assert same_parent(["/父/A", "/其他/B"]) is False
    assert same_parent([]) is False


def test_self_or_descendant():
    assert is_self_or_descendant("/剧", "/剧") is True
    assert is_self_or_descendant("/剧", "/剧/子") is True
    assert is_self_or_descendant("/剧", "/别的") is False
    assert is_self_or_descendant("/说明.txt", "/说明.txt") is True
    assert is_self_or_descendant("/说明.txt", "/其他") is False


def test_next_copy_name_keeps_extension_for_files():
    assert next_copy_name("a.txt", is_dir=False, attempt=0) == "a.txt"
    assert next_copy_name("a.txt", is_dir=False, attempt=1) == "a(1).txt"
    assert next_copy_name("a.txt", is_dir=False, attempt=2) == "a(2).txt"
    assert next_copy_name("漫剧", is_dir=True, attempt=1) == "漫剧(1)"
    assert next_copy_name("a.b.c", is_dir=True, attempt=1) == "a.b.c(1)"


def test_validate_targets_rejects_bad_sets():
    with pytest.raises(ValueError, match="目标目录"):
        validate_targets("/源", [])
    with pytest.raises(ValueError, match="同级"):
        validate_targets("/源", ["/a/1", "/b/2"])
    with pytest.raises(ValueError, match="自身"):
        validate_targets("/父/源", ["/父/源"])
    assert validate_targets("/父/源", ["/父/A", "/父/B"]) == ["/父/A", "/父/B"]

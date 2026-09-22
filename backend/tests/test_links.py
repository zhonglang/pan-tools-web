from app.links import parse_share_link, split_link_lines


def test_three_link_forms():
    query = parse_share_link("https://pan.baidu.com/s/1AbCdEf?pwd=ab12")
    labeled = parse_share_link("https://pan.baidu.com/s/1AbCdEf 提取码: cd34")
    spaced = parse_share_link("https://pan.baidu.com/s/1AbCdEf gh56")
    plain = parse_share_link("https://pan.baidu.com/s/1AbCdEf")
    assert (query.surl, query.password) == ("AbCdEf", "ab12")
    assert (labeled.surl, labeled.password) == ("AbCdEf", "cd34")
    assert (spaced.surl, spaced.password) == ("AbCdEf", "gh56")
    assert (plain.surl, plain.password) == ("AbCdEf", None)


def test_unparseable_link_is_none():
    assert parse_share_link("不是链接") is None
    assert parse_share_link("https://pan.baidu.com/disk/home") is None


def test_blank_lines_are_dropped():
    assert split_link_lines("  \nhttps://pan.baidu.com/s/1abc\n\n  第二行  ") == [
        "https://pan.baidu.com/s/1abc",
        "第二行",
    ]

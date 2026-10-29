from app.services.links import canonical_input, parse_share_link, share_chunks, split_link_lines, with_share_password


def test_three_link_forms():
    query = parse_share_link("https://pan.baidu.com/s/1AbCdEf?pwd=ab12")
    labeled = parse_share_link("https://pan.baidu.com/s/1AbCdEf 提取码: cd34")
    spaced = parse_share_link("https://pan.baidu.com/s/1AbCdEf gh56")
    plain = parse_share_link("https://pan.baidu.com/s/1AbCdEf")
    assert (query.surl, query.password) == ("AbCdEf", "ab12")
    assert (labeled.surl, labeled.password) == ("AbCdEf", "cd34")
    assert (spaced.surl, spaced.password) == ("AbCdEf", "gh56")
    assert (plain.surl, plain.password) == ("AbCdEf", None)


def test_with_share_password_appends_query():
    assert with_share_password("https://pan.baidu.com/s/1AbCdEf", "ab12") == (
        "https://pan.baidu.com/s/1AbCdEf?pwd=ab12"
    )
    assert with_share_password("https://pan.baidu.com/s/1AbCdEf?pwd=ab12", "zz99") == (
        "https://pan.baidu.com/s/1AbCdEf?pwd=ab12"
    )
    assert with_share_password("https://pan.baidu.com/s/1AbCdEf", None) == "https://pan.baidu.com/s/1AbCdEf"


def test_unparseable_link_is_none():
    assert parse_share_link("不是链接") is None
    assert parse_share_link("https://pan.baidu.com/disk/home") is None


def test_baidu_copy_card_is_one_link():
    card = (
        "【超级会员V4】通过百度网盘分享的文件：【韩剧】挑情丑闻\n"
        "链接:https://pan.baidu.com/s/1kBdgMqBHCFBpexkIfIpIZw?pwd=6666\u00a0\n"
        "复制这段内容打开「百度网盘APP 即可获取」"
    )
    chunks = share_chunks(card)
    assert len(chunks) == 1
    parsed = parse_share_link(chunks[0])
    assert parsed is not None
    assert (parsed.provider, parsed.surl, parsed.password, parsed.title) == (
        "baidu",
        "kBdgMqBHCFBpexkIfIpIZw",
        "6666",
        "【韩剧】挑情丑闻",
    )
    assert canonical_input(chunks[0]) == "https://pan.baidu.com/s/1kBdgMqBHCFBpexkIfIpIZw?pwd=6666"


def test_quark_copy_card_is_one_link():
    card = (
        "我用夸克网盘给你分享了「电影」，点击链接或复制整段内容，打开「夸克APP」即可获取。\n"
        "链接：https://pan.quark.cn/s/AbCdEf"
    )
    chunks = share_chunks(card)
    assert len(chunks) == 1
    parsed = parse_share_link(chunks[0])
    assert parsed is not None
    assert (parsed.provider, parsed.surl, parsed.title) == ("quark", "AbCdEf", "电影")


def test_plain_garbage_line_is_ignored():
    text = "https://pan.baidu.com/s/1AbCdEf ab12\n\n不是链接\nhttps://pan.baidu.com/s/1ZzYyXx cd34"
    assert len(share_chunks(text)) == 2


def test_chat_cards_keep_two_unique_links():
    text = (
        "阿木木\n"
        "2026年09月22日 22:20\n"
        "【超级会员V4】通过百度网盘分享的文件：本座的灵宠要上天\n"
        "链接:https://pan.baidu.com/s/1vAgOVmVLFol5EeVfVYnsMA?pwd=6666\u00a0\n"
        "复制这段内容打开「百度网盘APP 即可获取」\n"
        "\n"
        "阿木木\n"
        "2026年09月22日 22:20\n"
        "【超级会员V4】通过百度网盘分享的文件：《My Dear…\n"
        "链接:https://pan.baidu.com/s/1MMNAdvSgFtKBLNGa2DI8Ew?pwd=6666\u00a0\n"
        "复制这段内容打开「百度网盘APP 即可获取」\n"
        "\n"
        "链接:https://pan.baidu.com/s/1vAgOVmVLFol5EeVfVYnsMA?pwd=6666\n"
    )
    chunks = share_chunks(text)
    assert [parse_share_link(chunk).surl for chunk in chunks] == [
        "vAgOVmVLFol5EeVfVYnsMA",
        "MMNAdvSgFtKBLNGa2DI8Ew",
    ]


def test_blank_lines_are_dropped():
    assert split_link_lines("  \nhttps://pan.baidu.com/s/1abc\n\n  第二行  ") == [
        "https://pan.baidu.com/s/1abc",
        "第二行",
    ]

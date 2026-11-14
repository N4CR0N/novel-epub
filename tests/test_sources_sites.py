"""Royal Road ve NovelFull ayrıştırıcı testleri: ağ yok, küçük uydurma HTML'lerle."""
from bs4 import BeautifulSoup

from novel_epub.models import ChapterRef
from novel_epub.sources import source_for
from novel_epub.sources.novelfull import NovelFull
from novel_epub.sources.royalroad import RoyalRoad


class FakeFetcher:
    """URL -> HTML (soup/json) sözlüğüyle çalışan sahte getirici; istenen URL'leri kaydeder."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls: list[str] = []

    def _get(self, url):
        self.calls.append(url)
        return self.pages[url]

    def soup(self, url, **kw):
        return BeautifulSoup(self._get(url), "html.parser")

    def json(self, url, **kw):
        return self._get(url)


LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt."


# ---------------- Royal Road ----------------
RR_NOVEL = """<html><head><meta property="og:image" content="https://cdn.example/cover.jpg"></head><body>
<div class="fic-header"><div class="fic-title"><h1>Lorem Fiction</h1><h4><span>by </span><a href="/profile/1">Ipsum Author</a></h4></div></div>
<span class="fiction-info"><span class="tags"><a class="fiction-tag">Fantasy</a><a class="fiction-tag">Magic</a></span></span>
<div class="description"><div><p>Lorem summary one.</p><p>Lorem summary two.</p></div></div>
<table id="chapters" class="table"><tbody>
<tr class="chapter-row" data-url="/fiction/5/lorem-fiction/chapter/11/one"><td><a href="/fiction/5/lorem-fiction/chapter/11/one"> 1. One </a></td></tr>
<tr class="chapter-row" data-url="/fiction/5/lorem-fiction/chapter/12/two"><td><a href="/fiction/5/lorem-fiction/chapter/12/two">2. Two</a></td></tr>
<tr class="chapter-row" data-url="/fiction/5/lorem-fiction/chapter/12/two"><td><a href="/fiction/5/lorem-fiction/chapter/12/two">2. Two (kopya)</a></td></tr>
</tbody></table></body></html>"""

RR_CHAPTER = f"""<html><head><style>.cjkHIDDEN{{ display: none; speak: never; }} .shown{{color:red}}</style></head><body>
<div class="fic-header"><h1 class="font-white break-word">1. One</h1></div>
<div class="chapter-inner chapter-content"><p>{LOREM}</p><p class="cjkHIDDEN">Gizli korsan karsiti satir.</p>
<p>Lorem second <span class="cjkHIDDEN">gizli</span>paragraph here.</p><p class="shown">Third lorem paragraph.</p></div>
<a class="btn btn-primary" href="/fiction/5/lorem-fiction/chapter/12/two">Next<i></i>Chapter</a></body></html>"""


def test_royalroad_novel_and_url():
    assert RoyalRoad.novel_url("https://www.royalroad.com/fiction/5/lorem-fiction/chapter/11/one") == \
        "https://www.royalroad.com/fiction/5/lorem-fiction"
    base = "https://www.royalroad.com/fiction/5/lorem-fiction"
    ff = FakeFetcher({base: RR_NOVEL})
    src = source_for(base + "/chapter/11/one", ff)
    assert src.name == "royalroad"
    n = src.novel(base + "/chapter/11/one")
    assert (n.title, n.author, n.genres) == ("Lorem Fiction", "Ipsum Author", "Fantasy, Magic")
    assert n.cover_url == "https://cdn.example/cover.jpg"
    assert n.description == "Lorem summary one.\nLorem summary two."
    assert [(c.index, c.title) for c in n.chapters] == [(1, "1. One"), (2, "2. Two")]
    assert n.chapters[1].url == base + "/chapter/12/two"


def test_royalroad_chapter_removes_hidden():
    ref = ChapterRef(1, "1. One", "https://www.royalroad.com/fiction/5/lorem-fiction/chapter/11/one")
    ch = RoyalRoad(FakeFetcher({ref.url: RR_CHAPTER})).chapter(ref)
    assert ch.title == "1. One"
    assert ch.paragraphs == [LOREM, "Lorem second paragraph here.", "Third lorem paragraph."]
    assert ch.next_url == "https://www.royalroad.com/fiction/5/lorem-fiction/chapter/12/two"


# ---------------- NovelFull ailesi ----------------
def li(slug, n):
    return f'<li><a href="/lorem/chapter-{n}-{slug}.html" title="Chapter {n} - {slug}">Chapter {n} - {slug}</a></li>'


# 1) novelfull.com: sayfalı ul.list-chapter
NF_COM_P1 = f"""<html><body><div class="book"><img src="/uploads/cover.webp"></div>
<h3 class="title">Lorem Novel</h3><div class="info"><div>Author: <a href="/author/a">Ipsum A</a></div>
<div>Genre: <a href="/genre/x">Action</a>, <a href="/genre/y">Mecha</a></div></div>
<div class="desc-text"><p>Lorem desc.</p></div>
<ul class="list-chapter">{li('a', 1)}{li('b', 2)}</ul>
<ul class="pagination"><li><a href="/lorem.html?page=2">2</a></li><li><a href="/lorem.html?page=3">Last</a></li></ul></body></html>"""
NF_COM_P2 = f'<html><body><ul class="list-chapter">{li("c", 3)}{li("b", 2)}</ul></body></html>'
NF_COM_P3 = f'<html><body><ul class="list-chapter">{li("d", 4)}</ul></body></html>'

# 2) readnovelfull.com: ajax/chapter-archive
RNF_PAGE = """<html><head><meta property="og:image" content="https://img.example/c.jpg"></head><body>
<h3 class="title">Lorem Novel</h3><div id="rating" data-novel-id="42"></div>
<ul class="info"><li>Author: Ipsum A , Dolor B</li><li>Genre: Sci-fi , Action</li></ul>
<div class="desc-text">Lorem desc.</div></body></html>"""
RNF_ARCHIVE = f'<div><ul class="list-chapter">{li("a", 1)}{li("b", 2)}</ul><ul class="list-chapter">{li("c", 3)}</ul></div>'

# 3) NOVGO düzeni: JSON ajax-chapter-list
NG_PAGE = """<html><head><meta property="og:image" content="/uploads/thumb.jpg"></head><body><h1 class="tit">Lorem Novel</h1>
<div class="m-imgtxt"><div class="pic"><img src="/uploads/thumb.jpg"></div><div class="txt">
<div class="item"><div class="right"><a href="/author/a">Ipsum A</a></div></div>
<div class="item"><div class="right"><a href="/genre/x">Action</a></div></div></div></div>
<div class="m-desc"><div class="txt"><p>Lorem desc.</p></div></div>
<div class="m-newest2" id="list-chapter" data-novel-id="7" data-list-url="/ajax-chapter-list" data-total-page="2"></div></body></html>"""
NG_P1 = {"code": 200, "totalPage": 2, "html": li("a", 1) + li("b", 2)}
NG_P2 = {"code": 200, "totalPage": 2, "html": li("c", 3)}

CH_HTML = f"""<html><body><h1 class="chapter"><span class="chapter-title">Chapter 1 - a</span></h1>
<div id="chapter-content"><p>{LOREM}</p><p>Lorem two.</p><p>Lorem three.</p>
<div class="ads">reklam</div><script>x()</script></div>
<a href="/lorem/chapter-2-b.html">Next Chapter</a></body></html>"""


def test_novelfull_url_derivation():
    nu = NovelFull.novel_url
    assert nu("https://novelfull.com/index.php/lorem.html") == "https://novelfull.com/lorem.html"
    assert nu("https://novelfull.com/lorem/chapter-3-x.html") == "https://novelfull.com/lorem.html"
    assert nu("https://readnovelfull.com/lorem/chapter-3-x-v1.html") == "https://readnovelfull.com/lorem.html"
    for d in ("novelfull.com", "readnovelfull.com", "allnovelfull.net", "novelfull.net", "novgo.net"):
        assert source_for(f"https://{d}/lorem.html", None).name == "novelfull"


def titles(n):
    return [(c.index, c.title) for c in n.chapters]


def test_novelfull_com_paged():
    ff = FakeFetcher({
        "https://novelfull.com/lorem.html": NF_COM_P1,
        "https://novelfull.com/lorem.html?page=2": NF_COM_P2,
        "https://novelfull.com/lorem.html?page=3": NF_COM_P3,
    })
    n = NovelFull(ff).novel("https://novelfull.com/index.php/lorem.html")
    assert (n.title, n.author, n.genres, n.description) == ("Lorem Novel", "Ipsum A", "Action, Mecha", "Lorem desc.")
    assert n.cover_url == "https://novelfull.com/uploads/cover.webp"
    assert titles(n) == [(1, "Chapter 1 - a"), (2, "Chapter 2 - b"), (3, "Chapter 3 - c"), (4, "Chapter 4 - d")]
    assert n.chapters[3].url == "https://novelfull.com/lorem/chapter-4-d.html"


def test_readnovelfull_archive():
    ff = FakeFetcher({
        "https://readnovelfull.com/lorem.html": RNF_PAGE,
        "https://readnovelfull.com/ajax/chapter-archive?novelId=42": RNF_ARCHIVE,
    })
    n = NovelFull(ff).novel("https://readnovelfull.com/lorem.html")
    assert (n.author, n.genres, n.cover_url) == ("Ipsum A, Dolor B", "Sci-fi, Action", "https://img.example/c.jpg")
    assert [c.title for c in n.chapters] == ["Chapter 1 - a", "Chapter 2 - b", "Chapter 3 - c"]


def test_novgo_json_pages():
    ff = FakeFetcher({
        "https://allnovelfull.net/lorem.html": NG_PAGE,
        "https://allnovelfull.net/ajax-chapter-list?novelId=7&page=1&pageSize=50": NG_P1,
        "https://allnovelfull.net/ajax-chapter-list?novelId=7&page=2&pageSize=50": NG_P2,
    })
    n = NovelFull(ff).novel("https://allnovelfull.net/lorem.html")
    assert (n.title, n.author, n.genres, n.description) == ("Lorem Novel", "Ipsum A", "Action", "Lorem desc.")
    assert n.cover_url == "https://allnovelfull.net/uploads/thumb.jpg"
    assert titles(n) == [(1, "Chapter 1 - a"), (2, "Chapter 2 - b"), (3, "Chapter 3 - c")]


def test_novelfull_chapter():
    ref = ChapterRef(1, "Chapter 1 - a", "https://novelfull.com/lorem/chapter-1-a.html")
    ch = NovelFull(FakeFetcher({ref.url: CH_HTML})).chapter(ref)
    assert ch.title == "Chapter 1 - a"
    assert ch.paragraphs == [LOREM, "Lorem two.", "Lorem three."]
    assert ch.next_url == "https://novelfull.com/lorem/chapter-2-b.html"


# ---------------- libread (freewebnovel motoru) ----------------
def test_libread_routes_to_freewebnovel_engine():
    from novel_epub.sources.freewebnovel import FreeWebNovel

    assert FreeWebNovel.matches("https://libread.com/libread/lorem-novel-123/chapter-01")
    assert FreeWebNovel.novel_url("https://libread.com/libread/lorem-novel-123/chapter-01") == \
        "https://libread.com/libread/lorem-novel-123"


# ---------------- FanMTL / ReadWN ----------------
RW = "https://www.fanmtl.com"
RW_NOVEL = f"""<html><body><div class="novel-header"><figure class="cover"><img data-src="/d/file/c.jpg"></figure>
<h1 class="novel-title text2row">Lorem Talents</h1><div class="author"><span>Author:</span><span itemprop="author">Ipsum</span></div>
<div class="categories"><a>Fantasy</a><a>Lorem</a></div></div><div class="summary"><div class="content">Lorem özet.</div></div>
<ul class="chapter-list"><li><a href="/novel/lorem-talents_1.html" title="Chapter 1 One">x</a></li>
<li><a href="/novel/lorem-talents_2.html" title="Chapter 2 Two">x</a></li></ul>
<div class="pagination"><a href="/e/extend/fy.php?page=1&wjm=lorem-talents">2</a>
<a href="/e/extend/fy.php?page=2&wjm=lorem-talents">&gt;&gt;</a></div></body></html>"""


def _rw_page(n):
    return f'<ul class="chapter-list"><li><a href="/novel/lorem-talents_{n + 2}.html" title="Chapter {n + 2}">x</a></li></ul>'


def test_readwn_paginated_list_and_content():
    from novel_epub.sources.readwn import ReadWN

    ff = FakeFetcher({
        f"{RW}/novel/lorem-talents.html": RW_NOVEL,
        f"{RW}/e/extend/fy.php?page=1&wjm=lorem-talents": _rw_page(1),
        f"{RW}/e/extend/fy.php?page=2&wjm=lorem-talents": _rw_page(2),
        f"{RW}/novel/lorem-talents_1.html": f'<div class="chapter-content"><p>{LOREM}</p><p>{LOREM} 2</p></div>'
                                            f'<a rel="next" href="/novel/lorem-talents_2.html">Next</a>',
    })
    src = source_for(f"{RW}/novel/lorem-talents_7.html", ff)
    assert isinstance(src, ReadWN)
    n = src.novel(f"{RW}/novel/lorem-talents_7.html")
    assert (n.title, n.author, n.genres, n.source) == ("Lorem Talents", "Ipsum", "Fantasy, Lorem", "fanmtl")
    assert n.cover_url == f"{RW}/d/file/c.jpg" and n.description == "Lorem özet."
    assert [c.title for c in n.chapters] == ["Chapter 1 One", "Chapter 2 Two", "Chapter 3", "Chapter 4"]
    ch = src.chapter(n.chapters[0])
    assert len(ch.paragraphs) == 2 and ch.next_url == f"{RW}/novel/lorem-talents_2.html"


# ---------------- NovelBuddy ----------------
NB = "https://novelbuddy.com"


def test_novelbuddy_starts_at_first_chapter_and_follows_next():
    from novel_epub.sources.novelbuddy import NovelBuddy

    page = f"""<html><head><meta property="og:image" content="https://rs.example/c.png"></head><body>
    <h1>Lorem War</h1><a href="/authors/ipsum">Ipsum</a><ul>
    <li><a href="/lorem-war/chapter-120-late">Chapter 120</a></li><li><a href="/lorem-war/chapter-1-start">Chapter 1</a></li>
    <li><a href="/lorem-war/chapter-119-late">Chapter 119</a></li></ul></body></html>"""
    chap = f"""<html><body><h1 class="sr-only">Lorem War Chapter 1 Start</h1><nav><a href="/">Home</a></nav>
    <div><p>{LOREM}</p><p>{LOREM} b</p><p>{LOREM} c</p></div>
    <a class="inline-flex" href="/lorem-war/chapter-2-next">Next</a></body></html>"""
    ff = FakeFetcher({f"{NB}/lorem-war": page, f"{NB}/lorem-war/chapter-1-start": chap})
    src = source_for(f"{NB}/lorem-war/chapter-119-late", ff)
    assert isinstance(src, NovelBuddy)
    n = src.novel(f"{NB}/lorem-war/chapter-119-late")
    assert n.follow_next and n.title == "Lorem War" and n.author == "Ipsum"
    assert n.chapters[0].url == f"{NB}/lorem-war/chapter-1-start"
    ch = src.chapter(n.chapters[0])
    assert len(ch.paragraphs) == 3 and ch.next_url == f"{NB}/lorem-war/chapter-2-next"


# ---------------- Wattpad ----------------
def test_wattpad_api_story_and_part_link():
    from novel_epub.sources.wattpad import API, FIELDS, Wattpad

    story = {"title": "Lorem Story", "user": {"name": "ipsum"}, "cover": "https://img.example/c.jpg",
             "description": "Lorem.", "tags": ["romance", "lorem"],
             "parts": [{"id": 11, "title": "Intro", "url": "https://www.wattpad.com/11-lorem-intro"},
                       {"id": 12, "title": "Part Two", "url": "https://www.wattpad.com/12-lorem-two"}]}

    class Resp:
        def __init__(self, text):
            self.text = text

    class WF(FakeFetcher):
        def get(self, url, **kw):
            return Resp(self._get(url))

    ff = WF({f"{API}/story_parts/12?fields=groupId": {"groupId": "99"},
             f"{API}/stories/99?fields={FIELDS}": story,
             "https://www.wattpad.com/apiv2/?m=storytext&id=11": f'<p data-p-id="a">{LOREM}</p><p data-p-id="b">{LOREM} 2</p>'})
    src = source_for("https://www.wattpad.com/12-lorem-two", ff)
    assert isinstance(src, Wattpad)
    n = src.novel("https://www.wattpad.com/12-lorem-two")
    assert (n.title, n.author, n.genres) == ("Lorem Story", "ipsum", "romance, lorem")
    assert n.url == "https://www.wattpad.com/story/99" and [c.title for c in n.chapters] == ["Intro", "Part Two"]
    assert len(src.chapter(n.chapters[0]).paragraphs) == 2

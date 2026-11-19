"""Çeviri kalite denetimi: başlık kalıbı, seviye, eski kelime, İngilizce kalan kelime, sözlük, eksik çeviri, onarım turu."""
from __future__ import annotations

from novel_epub import quality
from novel_epub.models import Chapter


def test_titles_follow_one_pattern_without_invented_volume():
    n = quality.normalize_title
    assert n("Chapter 700 Lorem (1)", "Cilt 700 Felaket ve Nimet (1)", "tr") == "Bölüm 700: Felaket ve Nimet (1)"
    assert n("Chapter 709 Lorem (2)", "Cilt 7 Bölüm 709: Her Şeyi Ezmek (2)", "tr") == "Bölüm 709: Her Şeyi Ezmek (2)"
    assert n("Chapter 692 100-Year Lorem", "Cilt 692 100 Yıllık Kira", "tr") == "Bölüm 692: 100 Yıllık Kira"
    assert n("Chapter 5", "Cilt 1 ve Bölüm 5", "tr") == "Bölüm 5"
    assert n("Volume 2 Chapter 30: Lorem", "Cilt 2 Bölüm 30: İksir", "tr") == "Cilt 2 Bölüm 30: İksir"
    assert n("Chapter 9 - Lorem", "Kapitel 9: Ipsum", "de") == "Kapitel 9: Ipsum"
    assert n("Önsöz", "Önsöz", "tr") == "Önsöz"  # tanınmayan kalıba dokunulmaz


def test_levels_and_old_words():
    assert quality.fix_levels("Sv. 10'a, Lv.100'ü, (Sv. 2 %71), Level 5; Svetlana") == \
        "Seviye 10'a, Seviye 100'ü, (Seviye 2 %71), Seviye 5; Svetlana"
    found = dict(quality.archaic_words("Gelgelelim talebelerin ekseriyeti muvaffak olamaz; dâhi addedilir. Vakit geçti."))
    assert {"Gelgelelim", "talebelerin", "ekseriyeti", "muvaffak", "addedilir"} <= set(found)
    assert not any(w.lower().startswith("vakit") for w in found)  # bugün de doğal olan kelimeler sayılmaz


def test_leftover_english_and_glossary_misses():
    src = "Dean Ming covered the back of the senior brother on Spacetime Island."
    out = "Dean Ming, Spacetime Island'da kıdemli kardeşin arkasını kolladı; normal bir test."
    left = quality.leftover_english(src, out, quality.source_vocab([Chapter(1, "", "", [src])]))
    assert left == ["Dean", "Spacetime", "Island"]  # Ming ad; normal/test Türkçede de aynı
    assert quality.glossary_misses("He went to Myriad Star Island.", "Bin Yıldız Adası'na gitti.",
                                   {"Myriad Star Island": "Milyar Yıldız Adası"})
    assert not quality.glossary_misses("He went to Myriad Star Island.", "Milyar Yıldız Adası'na gitti.",
                                       {"Myriad Star Island": "Milyar Yıldız Adası"})
    bad = quality.suspicious_glossary({"Feather Fire City": "Feather Fire City", "Fei Qing": "Fei Qing",
                                       "Abyssal Mother Blood": "Abyssal Ana Kan", "Black Lotus Sect": "Kara Lotus Tarikatı"},
                                      {"abyssal", "city"})
    assert set(bad) == {"Feather Fire City", "Abyssal Mother Blood"}
    assert not quality.suspicious_glossary({"Tiger Fussen": "Tiger Fussen"}, {"tiger"})  # kişi adı aynen kalır
    assert "tiger" in quality.name_words({}, {"Tiger Fussen": "Tiger Fussen"})
    assert quality.restore_names({"Mr. Ninefish": "Bay Ninefish"}, {"Mr. Ninefish": ""}) == {}  # unvan çevrilir


def test_review_fixes_flagged_paragraphs_with_one_request():
    from novel_epub.translator import Translator

    src = Chapter(3, "Chapter 3 Lorem", "u", ["Dean Ming nodded to the students in the hall of the academy today.",
                                               "The lantern swayed while Arin counted the steps to the mill slowly."])
    out = Chapter(3, "Cilt 3 Lorem", "u", ["Dean Ming akademinin salonundaki talebelere başını salladı.",
                                            "Arin değirmene giden basamakları yavaşça sayarken fener sallandı."])
    tr = Translator.__new__(Translator)
    tr._init_state(model="gemini/x", lang="tr", log=lambda m: None)
    calls = []

    def fake_call(payload, schema=None, bad_retries=None, system=None):
        calls.append(payload)
        assert [len(i["issues"]) for i in payload["items"]] == [2]  # yalnız sorunlu paragraf: eski kelime + İngilizce
        return {"paragraphs": ["Dekan Ming akademinin salonundaki öğrencilere başını salladı."]}

    tr._call = fake_call
    got = tr.review([(src, out)], {}, quality.source_vocab([src]))[0]
    assert len(calls) == 1 and got.title == "Bölüm 3: Lorem"
    assert got.paragraphs[0].startswith("Dekan Ming") and got.paragraphs[1] == out.paragraphs[1]
    assert got.checked == quality.QUALITY_VERSION


def _pair(n):
    k = [3, 7, 4, 9, 5, 8, 6, 10]
    src = [f"Lorem {i} " + "dolor sit amet " * k[i % 8] for i in range(n)]
    out = [f"Türkçe {i} " + "kalem su ve ta " * k[i % 8] for i in range(n)]
    return [x.strip() for x in src], [x.strip() for x in out]


def test_alignment_finds_omitted_and_duplicated_paragraphs():
    src, out = _pair(8)
    dropped = out[:3] + out[4:]                      # 4. paragraf atlanmış
    assert ((3,), ()) in quality.align(src, dropped)
    ch_src = Chapter(1, "Chapter 1", "", src)
    issues, extra = quality.paragraph_issues(ch_src, Chapter(1, "Bölüm 1", "", dropped), "tr", {}, set())
    assert extra == {2: [src[3]]} and any(quality.OMITTED in x for x in issues[2][1])
    doubled = out[:5] + [out[4]] + out[5:]            # 5. paragraf iki kez
    issues, _ = quality.paragraph_issues(ch_src, Chapter(1, "Bölüm 1", "", doubled), "tr", {}, set())
    flagged = [i for i, (_, xs) in issues.items() if any("ikinci kez" in x for x in xs)]
    assert flagged == [4] and set(issues) == {4}  # karşılıksız kopya silinecek, asıl paragraf kalır
    merged = out[:2] + [out[2] + " " + out[3]] + out[4:]  # iki paragraf birleştirilmiş: sorun değil
    issues, extra = quality.paragraph_issues(ch_src, Chapter(1, "Bölüm 1", "", merged), "tr", {}, set())
    assert not extra and not issues


def test_review_inserts_missing_and_drops_duplicates():
    from novel_epub.translator import Translator

    src, out = _pair(6)
    draft = out[:2] + out[3:] + [out[5]]   # 2. atlanmış, sonuncusu tekrar
    tr = Translator.__new__(Translator)
    tr._init_state(model="gemini/x", lang="tr", log=lambda m: None)

    def fake_call(payload, schema=None, bad_retries=None, system=None):
        res = []
        for it in payload["items"]:
            if it.get("missing"):
                res.append(it["draft"] + "\n\n" + out[src.index(it["missing"][0])])
            elif any("ikinci kez" in x or "karşılığı" in x for x in it["issues"]):
                res.append("")
            else:
                res.append(it["draft"])
        return {"paragraphs": res}

    tr._call = fake_call
    got = tr.review([(Chapter(1, "Chapter 1", "", src), Chapter(1, "Bölüm 1", "", draft))], {}, set())[0]
    assert got.paragraphs == out


def test_short_paragraphs_with_equal_counts_stay_one_to_one():
    # gerçek bir bölümdeki uzunluk deseni: kısa satırlar atlanıp yanlış eşlenmemeli
    sl, ol = [38, 67, 109, 28, 38, 309, 60, 102], [43, 65, 87, 37, 59, 282, 57, 97]
    src = [("Fang Xinglong said " if i % 2 else "Xu Jingming said ") + "x" * (n - 18) for i, n in enumerate(sl)]
    out = [("Fang Xinglong dedi " if i % 2 else "Xu Jingming dedi ") + "y" * (n - 18) for i, n in enumerate(ol)]
    assert quality.align(src, out) == [((i,), (i,)) for i in range(8)]


def test_review_rejects_a_fix_that_replaces_the_paragraph():
    from novel_epub.translator import Translator

    src = ["Xu Jingming nodded at the dean today.", "Fang Xinglong asked how this could happen at all, frowning deeply."]
    out = ["Xu Jingming bugün Dean'e başını salladı.", "Fang Xinglong kaşlarını çatarak bunun nasıl olabildiğini sordu."]
    tr = Translator.__new__(Translator)
    tr._init_state(model="gemini/x", lang="tr", log=lambda m: None)
    tr._call = lambda payload, schema=None, bad_retries=None, system=None: {
        "paragraphs": ["Fang Xinglong kaşlarını çatarak bunun nasıl olabildiğini tekrar tekrar sordu durdu."] * len(payload["items"])}
    got = tr.review([(Chapter(1, "Chapter 1", "", src), Chapter(1, "Bölüm 1", "", out))], {}, set())[0]
    assert got.paragraphs == out  # başka paragrafın metni kabul edilmedi


def test_character_names_are_kept_but_titles_translated():
    chars = {"Tiger Fussen": "", "Dean Ming": "", "Five": "", "Spacetime Island Lord": ""}
    names = quality.name_words(chars)
    assert {"tiger", "fussen", "five", "ming"} <= names and "dean" not in names and "island" not in names
    src = "Tiger Fussen and Dean Ming met Five."
    assert quality.leftover_english(src, "Tiger Fussen ve Dean Ming, Five ile buluştu.", set(), names) == ["Dean"]
    assert quality.restore_names({"Tiger Fussen": "Kaplan Fussen", "Dean Ming": "Dekan Ming"}, chars) == \
        {"Tiger Fussen": "Tiger Fussen"}


def test_title_line_in_body_is_dropped_and_never_inserted():
    src = Chapter(580, "Chapter 580 Looming Shadow of a Lorem", "u",
                  ["580 Looming Shadow of a Lorem", "Redmond sat cross-legged and listened to the principal speaking.",
                   "The struggle over the treasures was an extinction event for the entire universe.", "Indeed, Redmond nodded."])
    out = Chapter(580, "Bölüm 580: Bir Lorem'in Belirsiz Gölgesi", "u",
                  ["Redmond bağdaş kurup oturdu ve müdürün konuşmasını dinledi.",
                   "Bölüm 580 Bir Lorem'in Belirsiz Gölgesi",
                   "Hazineler üzerindeki çekişme tüm evren için bir yok oluştu.", "Gerçekten de öyle, Redmond başını salladı."])
    fixed = quality.fix_chapter(src, out, "tr")
    assert len(fixed.paragraphs) == 3 and not fixed.paragraphs[1].startswith("Bölüm")
    _, extra = quality.paragraph_issues(src, Chapter(580, fixed.title, "u", fixed.paragraphs), "tr", {}, set())
    assert extra == {}  # kaynaktaki başlık satırı "atlanmış" sayılmaz
    body = Chapter(100, "Bölüm 100: Yetişim", "u", ["100 yıl geçti.", "a" * 50, "b" * 50, "c" * 50])
    assert quality.fix_chapter(Chapter(100, "Chapter 100 Lorem", "u", ["x"] * 4), body, "tr").paragraphs[0] == "100 yıl geçti."


def test_title_glued_to_first_paragraph_is_removed():
    assert quality._strip_title_prefix("514 Bölüm 514: Uzaylı Irklar (1) Genel Sekreter haritaya baktı.", 514,
                                       "Bölüm 514: Uzaylı Irklar (1)") == "Genel Sekreter haritaya baktı."
    assert quality._strip_title_prefix("Bölüm 573: Genel Gelişme. Xu Jingming tek başına duruyordu.", 573,
                                       "Bölüm 573: Genel Gelişme") == "Xu Jingming tek başına duruyordu."
    assert quality._strip_title_prefix("514 kişi haritaya baktı.", 514, "Bölüm 514: Uzaylı Irklar (1)") == "514 kişi haritaya baktı."
    assert quality._strip_title_prefix("Bölüm 586: Dokunmak “İlk onu mu?” Xu Jingming gülümsedi.", 586,
                                       "Bölüm 586: Ona Dokunmak") == "“İlk onu mu?” Xu Jingming gülümsedi."
    assert quality.normalize_title("Chapter 473 Lorem (1)", "Cilt N Bölüm 473 Qin Fangke (1)", "tr") == "Bölüm 473: Qin Fangke (1)"
    assert quality.normalize_title("Chapter 473 Lorem (1)", "Bölüm 473: N Bölüm 473 Qin Fangke (1)", "tr") == "Bölüm 473: Qin Fangke (1)"
    assert quality.normalize_title("Chapter 9 Lorem", "Bölüm 9: Nehir", "tr") == "Bölüm 9: Nehir"

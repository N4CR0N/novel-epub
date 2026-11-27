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


def _p(*words):
    return " ".join(words)


def test_drop_repeats_removes_doubled_paragraph_but_keeps_author_repeats():
    from novel_epub.quality import drop_repeats
    a = _p("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore")
    b = _p("Ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo")
    c = _p("Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur")
    src = Chapter(1, "Chapter 1", "u", [a, b, c])
    # Çeviri b'yi iki kez yazmış: biri tam, biri kısmi kopya
    out = Chapter(1, "Bölüm 1", "u", [a, b, " ".join(b.split()[:13]), c])
    fixed, n = drop_repeats(src, out)
    assert n == 1 and fixed.paragraphs == [a, b, c]
    # Kaynakta da aynı paragraf art arda geçiyorsa (yazarın tekrarı) dokunulmaz
    src2 = Chapter(1, "Chapter 1", "u", [a, b, b, c])
    out2 = Chapter(1, "Bölüm 1", "u", [a, b, b, c])
    assert drop_repeats(src2, out2)[1] == 0
    # Uzun paragrafın içinde geçen kısa cümle (12 kelimeden az) tekrar sayılmaz
    assert drop_repeats(src, Chapter(1, "Bölüm 1", "u", [a, b, " ".join(b.split()[:8]), c]))[1] == 0
    # Kısa satırlar (cevap, ünlem) tekrar sayılmaz
    out3 = Chapter(1, "Bölüm 1", "u", [a, "Evet.", "Evet.", b, c])
    assert drop_repeats(Chapter(1, "Chapter 1", "u", [a, "Yes.", "Yes.", b, c]), out3)[1] == 0


def test_drop_boundary_repeat_removes_next_chapter_start():
    from novel_epub.quality import drop_boundary_repeat
    a, b, c, d, e = (_p(*(f"w{i}{k}" for k in range(12))) for i in range(5))
    s1, s2 = Chapter(1, "1", "u", [a, b, c, d]), Chapter(2, "2", "u", [e, "z " * 10])
    o1 = Chapter(1, "1", "u", [a, b, c, d, e])  # sonraki bölümün ilk paragrafı da bu bölümün sonuna eklenmiş
    o2 = Chapter(2, "2", "u", [e, "z " * 10])
    fixed, n = drop_boundary_repeat(s1, o1, s2, o2)
    assert n == 1 and fixed.paragraphs == [a, b, c, d]
    # Kaynakta da bölüm sonu sonraki bölümün başında tekrar ediyorsa dokunulmaz
    s1b = Chapter(1, "1", "u", [a, b, c, e])
    assert drop_boundary_repeat(s1b, Chapter(1, "1", "u", [a, b, c, e]), s2, o2)[1] == 0


def test_drop_next_chapter_copy_when_site_merged_two_chapters():
    from novel_epub.quality import drop_next_chapter_copy
    own = [_p(*(f"a{i}x{k}" for k in range(14))) for i in range(8)]
    nxt = [_p(*(f"b{i}x{k}" for k in range(14))) for i in range(6)]
    src = Chapter(742, "742", "u", own + nxt)  # site 742. sayfaya 743'ü de koymuş
    out = Chapter(742, "742", "u", [p.upper() for p in own + nxt])
    fixed, n = drop_next_chapter_copy(src, out, Chapter(743, "743", "u", nxt))
    assert n == 6 and fixed.paragraphs == [p.upper() for p in own]
    # Yeniden çalıştırınca bir daha kesmez
    assert drop_next_chapter_copy(src, fixed, Chapter(743, "743", "u", nxt))[1] == 0
    # Birleşme yoksa dokunulmaz
    assert drop_next_chapter_copy(Chapter(742, "742", "u", own), Chapter(742, "742", "u", own),
                                  Chapter(743, "743", "u", nxt))[1] == 0


def test_drop_repeats_removes_second_translation_in_other_words():
    from novel_epub.quality import drop_repeats
    words = [f"{c}{d}kelime" for c in "abcdefghij" for d in "klmnopqrst"]  # 100 farklı uydurma kelime
    fill = [" ".join(words[i:i + 20]) for i in range(40, 100, 20)]
    a, b = " ".join(words[:6]), " ".join(words[6:30])
    # Aynı kaynak paragrafın ikinci çevirisi: iki paragraf tek paragraf olmuş, birkaç kelime değişmiş
    again = " ".join(words[:6] + words[6:26] + ["zzbaska", "zyfarkli", "zxyeni", "zwobir"])
    src = Chapter(5, "Chapter 5", "u", [fill[0], "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
                                        "eiusmod tempor incididunt ut labore et dolore magna aliqua enim", fill[1]])
    out = Chapter(5, "Bölüm 5", "u", [fill[0], a, b, again, fill[1]])
    fixed, n = drop_repeats(src, out)
    assert n == 1 and fixed.paragraphs == [fill[0], a, b, fill[1]]
    # Birbirine benzemeyen art arda paragraflara dokunulmaz
    assert drop_repeats(src, Chapter(5, "Bölüm 5", "u", [fill[0], fill[1], fill[2]]))[1] == 0


def test_term_candidates_finds_names_used_mid_sentence():
    from novel_epub.quality import term_candidates
    paras = [
        "Lorem ipsum the Azure Cloud Sect dolor sit amet. Then Ming Kai nodded at the Azure Cloud Sect elder.",
        "Suddenly the wind rose. Consectetur adipiscing Ming Kai elit, sed do the Azure Cloud Sect gate.",
        "Suddenly it rained. However Ming Kai smiled. Sed ut perspiciatis Ming Kai unde omnis.",
        "Suddenly nothing. The Dean of the academy said hello to Ming Kai and the Dean left.",
    ]
    cands = term_candidates([Chapter(1, "1", "u", paras)], {"Dean": "Dekan"})
    names = [c["source"] for c in cands]
    assert names[:2] == ["Ming Kai", "Azure Cloud Sect"]  # sıklık sırası
    assert "Suddenly" not in names and "However" not in names  # yalnız cümle başında geçenler
    assert "Dean" not in names  # sözlükte zaten var
    assert all(c["context"] for c in cands[:2])


def test_build_glossary_adds_new_terms_with_best_model_and_keeps_existing():
    from novel_epub.translator import GeminiTranslator
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("iyi, kotu", log=lambda m: None)
    seen = []

    def fake(payload, schema=None, bad_retries=None, system=None):
        seen.append((tr.model, [t["source"] for t in payload.get("terms", [])]))
        return {"new_terms": [{"source": "Azure Cloud Sect", "target": "Gök Mavisi Bulut Tarikatı"},
                              {"source": "Ming Kai", "target": "Ming Kai"},
                              {"source": "Dean", "target": "Dekan Bey"}]}

    tr._call_model = fake
    paras = ["Lorem the Azure Cloud Sect ipsum.", "Dolor Ming Kai and the Azure Cloud Sect.",
             "Sit Ming Kai amet the Azure Cloud Sect.", "Amet Ming Kai the Dean."]
    out = tr.build_glossary([Chapter(1, "1", "u", paras)], {"Dean": "Dekan"})
    assert seen and seen[0][0] == "gemini/iyi" and "Azure Cloud Sect" in seen[0][1]
    assert out == {"Azure Cloud Sect": "Gök Mavisi Bulut Tarikatı", "Ming Kai": "Ming Kai"}  # Dean'e dokunmaz


def test_number_written_in_turkish_words_is_not_a_mismatch():
    from novel_epub.quality import paragraph_issues, tr_number_words
    assert tr_number_words(137) == "yüzotuzyedi" and tr_number_words(1500) == "binbeşyüz"
    assert tr_number_words(2) == "iki" and tr_number_words(500) == "beşyüz"
    src = Chapter(1, "Chapter 1", "u", ["Lorem ipsum 137 dolor sit amet with 500 stones and 3 days."])
    ok = Chapter(1, "Bölüm 1", "u", ["Lorem ipsum yüz otuz yedi dolor, beş yüz taş ve üç gün."])
    bad = Chapter(1, "Bölüm 1", "u", ["Lorem ipsum yüz dolor, beş yüz taş ve üç gün."])
    issues_ok, _ = paragraph_issues(src, ok, "tr", {}, set())
    issues_bad, _ = paragraph_issues(src, bad, "tr", {}, set())
    assert not any("sayı" in m for _, lst in issues_ok.values() for m in lst)
    assert any("137" in m for _, lst in issues_bad.values() for m in lst)


def test_tr_harmonize_and_replace_term_keep_turkish_suffixes():
    from novel_epub.quality import replace_term, tr_harmonize
    assert tr_harmonize("ün", "Tribün", "Felaket") == "in"
    assert tr_harmonize("de", "Tribün", "Felaket") == "te"
    assert tr_harmonize("u", "Dragon", "Ejderha") == "yı"
    assert tr_harmonize("yı", "Bela", "Felaket") == "i"
    out, n = replace_term("Altıncı Tribün'e ulaştı. Tribünde kaldı, Tribün'ün gücü büyüktü. Tribünler geldi.",
                          "Tribün", "Felaket")
    assert out == "Altıncı Felaket'e ulaştı. Felakette kaldı, Felaket'in gücü büyüktü. Felaketler geldi." and n == 4
    out, n = replace_term("mahkeme kuruldu. Mahkemeye gitti.", "mahkeme", "saray")
    assert out == "saray kuruldu. Saraya gitti." and n == 2


def test_glossary_audit_items_rank_by_frequency_with_aligned_examples():
    from novel_epub.quality import glossary_audit_items
    src = {i: Chapter(i, f"c{i}", "u", [f"Lorem the Azure Gate ipsum {i}.", "Dolor Ming Kai sit amet the Azure Gate.",
                                        "Amet the Iron Hall ipsum Azure Gate."]) for i in range(1, 4)}
    res = {i: Chapter(i, f"b{i}", "u", [f"Lorem Mavi Kapı ipsum {i}.", "Dolor Ming Kai sit amet Mavi Kapı.",
                                        "Amet Demir Salon ipsum Mavi Kapı."]) for i in range(1, 4)}
    items = glossary_audit_items(src, res, {"Azure Gate": "Mavi Kapı", "Iron Hall": "Demir Salon", "Ming Kai": "Ming Kai"})
    assert [it["source"] for it in items] == ["Azure Gate", "Iron Hall"]  # kişi adı (aynı karşılık) hariç
    assert items[0]["count"] == 9 and items[0]["examples"][0]["translation"].startswith("Lorem Mavi Kapı")


def test_glossary_audit_fixes_terms_in_glossary_and_translated_chapters(tmp_path):
    from novel_epub import pipeline
    from novel_epub.store import BookStore
    from novel_epub.models import Novel
    store = BookStore(tmp_path, Novel(url="u", title="k", source="t"))
    src = {i: Chapter(i, f"c{i}", "u", [f"He reached the Sixth Tribulation {i}.", "The Tribulation came.",
                                        "The Tribulation was near, Tribulation again."]) for i in range(1, 4)}
    res = {i: Chapter(i, f"b{i}", "u", [f"Altıncı Tribün'e ulaştı {i}.", "Tribün geldi.",
                                        "Tribün yakındı, yine Detsizlik."]) for i in range(1, 4)}
    glossary = {"Tribulation": "Tribün", "Sixth Tribulation": "Altıncı Tribün", "After": "Sonra"}
    seen = []

    class FakeTr:
        model = "sahte"

        def audit_glossary(self, items):
            seen.append([it["source"] for it in items])
            return {"Tribulation": ("Felaket", ["Detsizlik"])}, ["After"]

    job = pipeline.Job(pipeline.Options(url="u", translate=True))
    t = FakeTr()
    job._glossary_audit(t, t.audit_glossary, src, res, glossary, store)
    assert "Tribulation" in seen[0]
    assert glossary == {"Tribulation": "Felaket", "Sixth Tribulation": "Altıncı Felaket"}
    assert res[2].paragraphs == ["Altıncı Felaket'e ulaştı 2.", "Felaket geldi.", "Felaket yakındı, yine Felaket."]
    assert store.load_tr(2).paragraphs == res[2].paragraphs
    assert store.load_glossary_audit()["fixes"]["Tribulation"][:2] == ["Tribün", "Felaket"]


def test_drop_repeats_removes_retranslation_shorter_than_the_previous_paragraph():
    from novel_epub.quality import drop_repeats
    a = ("Lorem altıncı hazine cübbesi karşılığında ödeyebilir Mengus eliyle hareket yaparak Pangus bıraktığı "
         "değerli hazineden birini çıkardı. Mengus doğal olarak yedinci kabağını çıkarmaya cesaret edemezdi. "
         "Geride kalan eşyalar balyoz belirgindi tescilli silahıydı cübbenin bağlayabilecek özelliği yoktu. "
         "Ayrıca pazarda satıcılar fiyatları yükseltti tüccarlar kervanlar yolculuk.")
    b = ("Lorem altıncı hazine cübbesi karşılığında ödeyebilir Mengus elinin hareketiyle Pangus geride bıraktığı "
         "değerli hazineden birini çıkardı. Mengus doğal olarak yedinci kabağını çıkarmaya cesaret edemedi. "
         "Geride kalan eşyalar balyoz belirgindi farika silahıydı cübbe bağlayabilecek özelliğe sahip değildi.")
    src = Chapter(1, "c", "u", ["Lorem ipsum dolor sit amet one.", "A long English paragraph about the robe and gourd "
                                "and the hammer that he took out carefully from his storage space ring."])
    out = Chapter(1, "b", "u", ["Lorem ipsum bir.", a, b])
    fixed, n = drop_repeats(src, out)
    assert n == 1 and fixed.paragraphs == ["Lorem ipsum bir.", a]


def test_audit_glossary_keeps_only_known_terms_and_real_changes():
    from novel_epub.translator import GeminiTranslator
    tr = GeminiTranslator.__new__(GeminiTranslator)
    tr._init_state("iyi", log=lambda m: None)

    def fake(payload, schema=None, bad_retries=None, system=None):
        assert "fixes" in schema["properties"] and len(payload["terms"]) == 3
        return {"fixes": [{"source": "Court", "target": "Saray", "wrong_forms": ["Mahkemesi", "Saray"]},
                          {"source": "Lorem", "target": "Ipsum"}, {"source": "Gate", "target": "Kapı"}],
                "remove": ["After", "Nope"]}

    tr._call_model = fake
    items = [{"source": "Court", "current": "Mahkeme", "count": 9, "examples": []},
             {"source": "Gate", "current": "Kapı", "count": 5, "examples": []},
             {"source": "After", "current": "Sonra", "count": 4, "examples": []}]
    fixes, remove = tr.audit_glossary(items)
    assert fixes == {"Court": ("Saray", ["Mahkemesi"])} and remove == ["After"]


def test_zero_width_characters_do_not_hide_terms():
    from novel_epub.cleaner import clean_paragraphs
    from novel_epub.quality import glossary_audit_items
    assert clean_paragraphs(["The‌ ‌Heavenly‌ ‌Court came."]) == ["The Heavenly Court came."]
    src = {1: Chapter(1, "c", "u", ["The‌ ‌Heavenly‌ ‌Court came."] * 3)}
    res = {1: Chapter(1, "b", "u", ["Cennet Mahkemesi geldi."] * 3)}
    assert [it["source"] for it in glossary_audit_items(src, res, {"Heavenly Court": "Cennet Mahkemesi"})] == ["Heavenly Court"]


def test_replace_term_uses_n_buffer_for_compound_nouns():
    from novel_epub.quality import replace_term
    out, _ = replace_term("Yılan Komutan'ı, Yılan Komutan'da, Yılan Komutan'la.", "Yılan Komutan", "Ejderha Yılan Komutanı")
    assert out == "Ejderha Yılan Komutanı'nı, Ejderha Yılan Komutanı'nda, Ejderha Yılan Komutanı'yla."
    out, _ = replace_term("Kara Bedeni'nde, Kara Bedeni'ne.", "Kara Bedeni", "Kara Beden")
    assert out == "Kara Beden'de, Kara Beden'e."

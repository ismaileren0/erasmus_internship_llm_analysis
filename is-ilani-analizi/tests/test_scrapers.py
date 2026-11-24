"""
İnternete bağlanmadan çalışan testler: örnek HTML dosyalarıyla ayrıştırıcıları ve
Selenium'un kaydır/tıkla mantığını dener.   Çalıştırma:  python -m pytest -q
"""
import shutil
from pathlib import Path

import pytest

import json

from scrapers import youthall_bs4 as yh
from scrapers import linkedin_selenium as li
from scrapers import eurodesk_bs4 as ed
from scrapers import eures_api as eu
from scrapers.common import country_iso, erasmus_status
from pipeline.skills import canonical, keyword_skills

FIX = Path(__file__).parent / "fixtures"


def test_youthall_list():
    cards = yh.parse_list_page((FIX / "youthall_list.html").read_text(encoding="utf-8"))
    assert len(cards) == 2
    c = cards[0]
    assert c["title"] == "LOG-in Winter Staj Programı"
    assert c["company"] == "Logo Yazılım"
    assert c["job_type"] == "Stajyer" and c["deadline"] == "22.11.2026" and c["location"] == "İstanbul"
    assert cards[1]["url"].startswith("https://www.youthall.com/tr/carrefoursa/")
    assert cards[1]["location"] == "Hibrit"        # bilinmeyen ikonlu etiket yedek alana düşer
    assert all("yetenek-programlari" not in c["url"] for c in cards)   # yan reklam kutusu atlandı


def test_youthall_foreign_cities():
    opts = yh.parse_city_options((FIX / "youthall_list.html").read_text(encoding="utf-8"))
    assert ("302", "Münih") in opts and ("1", "İstanbul") in opts
    assert yh.foreign_cities(opts) == [("302", "Münih"), ("2262", "Amsterdam")]
    url = yh.build_europe_url(["302", "2262"], 2)
    assert "city%5B%5D=302&city%5B%5D=2262" in url and "type%5B%5D=internship" in url and url.endswith("page=2")


def test_eurodesk_parse():
    data = json.loads((FIX / "eurodesk_search.json").read_text(encoding="utf-8"))
    progs = {p["pid"]: p for p in ed.parse_programmes(data["open"]["html"])}
    assert set(progs) == {"19661", "20966"}
    ecb = progs["19661"]
    assert ecb["lang"] == "eu" and ecb["title"] == "ECB Traineeships"
    assert ecb["subtitle"] == "Work experience opportunities for students"
    assert ecb["facts"]["Deadline"] == "20/11/2026"
    assert "monthly grant from €1,170" in ecb["description"] and "text-decoration" not in ecb["description"]
    assert ecb["apply_url"].startswith("https://www.ecb.europa.eu")
    assert progs["20966"]["lang"] == "eu" and "Python" in progs["20966"]["description"]   # 'ro' sürüm yerine 'eu'


def test_eures_parse():
    data = json.loads((FIX / "eures_search.json").read_text(encoding="utf-8"))
    jobs = eu.parse_results(data, "internship")
    assert len(jobs) == 2
    assert jobs[0].country == "Avusturya" and jobs[0].company == "OMV" and jobs[0].method == "json-api"
    assert "German" in jobs[0].description and jobs[0].posted_date.startswith("2026-11")
    assert jobs[1].title == "Data Analytics Intern"            # İngilizce çeviri tercih edildi
    assert jobs[1].country == "Almanya"
    q = eu.build_query("Praktikum", countries=["DE"])
    assert q["keywords"][0]["keyword"] == "Praktikum" and q["locationCodes"] == ["de"]


def test_countries():
    assert country_iso("Rotterdam, South Holland, Netherlands") == "NL"
    assert country_iso("Berlin, Berlin, Germany") == "DE"
    assert country_iso("Münih") == "DE"
    assert country_iso("Croatia") == "HR"
    assert country_iso("European Union") == ""
    assert erasmus_status("NL") == "Evet" and erasmus_status("TR") == "Hayır"
    assert erasmus_status("GB") == "2027'den itibaren" and erasmus_status("") == "Bilinmiyor"


def test_youthall_detail():
    d = yh.parse_detail_page((FIX / "youthall_detail.html").read_text(encoding="utf-8"))
    assert "Java, C# veya Python" in d["description"]
    assert "• SQL ve Git" in d["description"]
    assert d["features"]["Departman"].startswith("Bilgisayar Yazılım")
    assert d["features"]["Çalışma Lokasyonları"] == "Online, Remote"
    assert d["company"] == "Logo Yazılım"
    assert yh.job_id_from_url("https://www.youthall.com/tr/LogoYazilim/log-in-winter-staj-programi_34/") \
        == "LogoYazilim/log-in-winter-staj-programi_34"


def test_linkedin_job_page():
    d = li.parse_job_page((FIX / "linkedin_job.html").read_text(encoding="utf-8"))
    assert "Docker, Kubernetes" in d["description"]
    assert d["criteria"]["İstihdam türü"] == "Tam Zamanlı"


@pytest.mark.skipif(not (shutil.which("google-chrome") or shutil.which("chromium")), reason="Chrome yok")
def test_linkedin_selenium_scroll_and_parse():
    """Selenium: modalı kapat, 'daha fazla' butonuyla kartları yükle, BS4 ile ayrıştır."""
    driver = li.make_driver(headless=True)
    try:
        driver.get((FIX / "linkedin_search.html").resolve().as_uri())
        li.dismiss_modal(driver)
        assert not driver.find_elements("id", "modal")
        count = li.load_more_cards(driver, target=50, max_rounds=10)
        assert count == 12                      # sayfadaki tüm ilanlar yüklendi
        cards = li.parse_search_results(driver.page_source)
        assert len(cards) == 12
        assert cards[0]["job_id"] == "4480000000"
        assert cards[0]["title"] == "Junior Python Developer 0"
        assert cards[0]["posted_date"].startswith("2026-11")
    finally:
        driver.quit()


def test_skills():
    assert keyword_skills("Python, SQL ve Docker bilen; React tecrübesi") == ["Docker", "Python", "React", "SQL"]
    assert "Java" not in keyword_skills("JavaScript bilgisi")
    assert canonical("python3") == "Python"
    assert canonical("MS Excel") == "Excel"
    assert canonical("PostgreSQL") == "SQL"
    assert canonical("javascript") == "JavaScript"
    assert canonical("Figma") == "Figma/UI-UX"
    assert canonical("problem çözme") == "Problem çözme"


def test_eurodesk_real_template():
    """Siteden alınmış gerçek bir <template> bloğu (paylaşım kısmı kısaltıldı)."""
    progs = ed.parse_programmes((FIX / "eurodesk_real_template.html").read_text(encoding="utf-8"))
    assert len(progs) == 1
    p = progs[0]
    assert p["title"] == "Eurojust Traineeships" and p["lang"] == "eu"
    assert "EUR 1500" in p["description"] and "calendarData" not in p["description"]
    assert "19/11/2026" in p["facts"].values()
    assert p["apply_url"] == "https://www.eurojust.europa.eu/about-us/jobs/traineeships"


def test_save_jobs_merge(tmp_path, monkeypatch):
    import config
    from scrapers.common import Job, save_jobs
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    save_jobs([Job(source="x", method="m", job_id="1", url="u", title="A")], "t")
    data = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    data[0]["first_seen"] = "2026-11-01"
    (tmp_path / "t.json").write_text(json.dumps(data), encoding="utf-8")
    save_jobs([Job(source="x", method="m", job_id="1", url="u", title="A2"),
               Job(source="x", method="m", job_id="2", url="u", title="B")], "t")
    rows = {r["job_id"]: r for r in json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))}
    assert set(rows) == {"1", "2"}
    assert rows["1"]["first_seen"] == "2026-11-01" and rows["1"]["title"] == "A2"


def test_language_and_match():
    from pipeline.clean import detect_language
    from pipeline.match import score_row
    assert detect_language("We are looking for an intern to join our team and you will learn") == "en"
    assert detect_language("Wir suchen einen Praktikanten für unser Team und du bist mit dabei") == "de"
    r = {"teknik_beceriler": ["python3", "FastAPI", "Kubernetes"], "erasmus_son": "Uygun", "donem_uyumu": "Uyumlu",
         "ingilizce_yeterli": True, "yerel_dil_sarti": [], "seviye": "Stajyer"}
    p, matched, missing = score_row(r)
    assert matched == ["Python", "Django/Flask"] and missing == ["Kubernetes"]
    assert p == 30 + 20 + 15 + round(25 * 2 / 3) + 10


def test_wikidata_universities():
    from scrapers.universities_wikidata import parse_bindings
    data = json.loads((FIX / "wikidata_pl.json").read_text(encoding="utf-8"))
    rows = {r["wikidata_id"]: r for r in parse_bindings(data, "PL")}
    assert set(rows) == {"Q1", "Q2", "Q4"}                       # etiketsiz kayıt (Q3) atlandı
    assert rows["Q2"]["website"] == "https://en.uni.lodz.pl/"    # birden çok site: ilki
    assert rows["Q2"]["type"] == "public university, university"
    assert rows["Q1"]["teknik_odakli"] and not rows["Q2"]["teknik_odakli"]
    assert rows["Q4"]["country"] == "Polonya" and rows["Q4"]["city"] == "Gliwice"


def test_grounding():
    from pipeline.skills import grounded
    text = "We use Python, PostgreSQL and data analysis. Fluent English."
    assert grounded("Python", text) and grounded("SQL", text) and grounded("Veri Analizi", text)
    assert not grounded("Excel", text) and not grounded("SAP", text)

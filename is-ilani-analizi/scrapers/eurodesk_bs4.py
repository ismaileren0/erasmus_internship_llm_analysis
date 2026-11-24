"""
YÖNTEM 1: requests + Beautiful Soup  (sunucudan gelen HTML'i ayrıştırma)
======================================================================
Kaynak: Eurodesk Opportunity Finder — https://programmes.eurodesk.eu/internships
        Avrupa Komisyonu destekli Eurodesk ağının staj programı listesi
        (AB kurumlarının stajları, IAESTE, Digital Opportunity Traineeships vb.)

Nasıl çalışıyor?
  Sayfa ilanları "/search?subcategories[internships]=internships&page=N" adresinden alıyor.
  Bu adres JSON döndürüyor, ama JSON'un içindeki alanlar (open.html, upcoming.html) düz HTML.
  Her programın tüm detayları bu HTML'de bir <template id="programme" data-hash="<id>-<dil>">
  etiketinin içinde hazır duruyor. Yani tarayıcıya gerek yok: requests ile indirip
  Beautiful Soup ile ayrıştırmak yeterli.

robots.txt: "User-agent: * / Disallow:" — tüm siteye izin veriyor. Yine de istekler arası bekliyoruz.

Çalıştırma:  python -m scrapers.eurodesk_bs4
"""
from __future__ import annotations

import argparse
import json
import re
import time

import requests
from bs4 import BeautifulSoup

import config
from scrapers.common import PARSER, Job, clean, html_to_text, polite_sleep, save_jobs

BASE = "https://programmes.eurodesk.eu"
SEARCH_URL = BASE + "/search?subcategories%5Binternships%5D=internships&page={page}"


def parse_programmes(html: str) -> list[dict]:
    """JSON'dan gelen HTML parçasındaki <template id="programme"> bloklarını ayrıştırır.
    Aynı program birden çok dilde gelebilir; İngilizce/AB ('-eu') sürümü tercih edilir."""
    soup = BeautifulSoup(html, PARSER)
    by_id: dict[str, dict] = {}
    for tpl in soup.select('template#programme, template[id="programme"]'):
        h = tpl.get("data-hash", "")
        pid, _, lang = h.partition("-")
        if not pid:
            continue
        if pid in by_id and by_id[pid]["lang"] == "eu":
            continue                                   # zaten İngilizce sürüm var
        if pid in by_id and lang != "eu":
            continue
        # Not: bs4, <template> içindeki metni get_text()'te saymaz; içeriği ayrı bir belge olarak ayrıştırıyoruz
        inner = BeautifulSoup(tpl.decode_contents(), PARSER)
        g = lambda role: inner.select_one(f'[data-role="{role}"]')   # noqa: E731
        title_box = g("title")
        title, subtitle = "", ""
        if title_box:
            parts = [clean(d.get_text()) for d in title_box.find_all("div", recursive=False)]
            title = parts[0] if parts else clean(title_box.get_text())
            subtitle = parts[1] if len(parts) > 1 else ""
        # "hero" kutusunda ikon + değer satırları: Age, Deadline ...
        facts = {}
        hero = g("hero")
        if hero:
            for row in hero.select("div.items-center, div.flex.items-center"):
                img, span = row.find("img"), row.find("span")
                if img and span:
                    facts[clean(img.get("alt", ""))] = clean(span.get_text())
        additional = [clean(s.get_text()) for s in (g("additional").find_all("span") if g("additional") else [])]
        body = g("body")
        if body:
            for s in body.find_all("style"):
                s.decompose()
        more = inner.select_one('a[data-role="button"]')
        by_id[pid] = {
            "pid": pid, "lang": lang, "title": title, "subtitle": subtitle,
            "description": html_to_text(str(body)) if body else "",
            "facts": facts, "additional": additional,
            "apply_url": more.get("href", "") if more else "",
        }
    return list(by_id.values())


LIST_PAGE = BASE + "/en?subcategories%5Binternships%5D=internships"


def _decode(text: str, where: str) -> dict | None:
    """Gelen metni JSON'a çevirir; olmazsa ilk satırları göstererek nedenini yazar."""
    t = (text or "").lstrip()
    if t.startswith("{"):
        try:
            return json.loads(t)
        except ValueError:
            pass
    hint = re.sub(r"\s+", " ", t[:200])
    print(f"  ! Eurodesk ({where}) JSON döndürmedi. Gelen yanıtın başı: {hint!r}")
    return None


def fetch_page(session: requests.Session, page: int) -> dict | None:
    try:
        r = session.get(SEARCH_URL.format(page=page), timeout=30,
                        headers={"Accept": "application/json, text/html, */*",
                                 "X-Requested-With": "XMLHttpRequest", "Referer": LIST_PAGE})
    except requests.RequestException as e:
        print(f"  ! Eurodesk bağlantı hatası: {e}")
        return None
    if r.status_code != 200:
        print(f"  ! Eurodesk HTTP {r.status_code} (sayfa {page}) — büyük olasılıkla bot koruması")
        return None
    return _decode(r.text, f"requests, sayfa {page}")


def fetch_pages_requests(max_pages: int):
    """Önce düz requests ile dener (asıl yöntem)."""
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get(LIST_PAGE, timeout=30)          # ana sayfayı ziyaret et: çerezleri (XSRF vb.) al
    except requests.RequestException:
        pass
    for page in range(1, max_pages + 1):
        data = fetch_page(s, page)
        if data is None:
            return
        yield page, data
        polite_sleep()


def fetch_pages_browser(max_pages: int, headless: bool = True):
    """Yedek yol: requests engellenirse gerçek Chrome'u (Selenium) açıp aynı adresi
    TARAYICININ İÇİNDEN fetch() ile ister. Bot koruması gerçek tarayıcıyı geçirir."""
    from scrapers.linkedin_selenium import make_driver
    driver = make_driver(headless=headless)
    try:
        driver.get(LIST_PAGE)
        time.sleep(5)                          # koruma sayfasının kendini doğrulaması için bekle
        driver.set_script_timeout(60)
        for page in range(1, max_pages + 1):
            text = driver.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "fetch(arguments[0], {headers: {'X-Requested-With': 'XMLHttpRequest'}})"
                ".then(r => r.text()).then(done).catch(e => done('HATA ' + e));",
                SEARCH_URL.format(page=page))
            data = _decode(text, f"tarayıcı, sayfa {page}")
            if data is None:
                return
            yield page, data
            polite_sleep()
    finally:
        driver.quit()


def scrape(max_pages: int = config.EURODESK_MAX_PAGES, use_browser: bool = False) -> list[Job]:
    found: dict[str, dict] = {}
    method = "requests+bs4"

    def collect(pages) -> int:
        n = 0
        for page, data in pages:
            html = "".join((data.get(k) or {}).get("html", "") for k in ("open", "upcoming"))
            progs = parse_programmes(html)
            new = [p for p in progs if p["pid"] not in found]
            for p in new:
                found[p["pid"]] = p
            n += len(new)
            print(f"[eurodesk] sayfa {page}: {len(progs)} program, {len(new)} yeni")
            if not data.get("has-more") or not new:
                break
        return n

    if not use_browser:
        collect(fetch_pages_requests(max_pages))
    if not found:
        print("[eurodesk] requests ile veri alınamadı -> Selenium ile tarayıcı içinden deneniyor...")
        method = "selenium+bs4"
        try:
            collect(fetch_pages_browser(max_pages))
        except Exception as e:  # noqa: BLE001
            print(f"  ! Tarayıcı yolu da başarısız: {e}")

    jobs = []
    for p in found.values():
        deadline = next((v for v in p["facts"].values() if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), "")
        jobs.append(Job(
            source="eurodesk", method=method, job_id=p["pid"],
            url=p["apply_url"] or f"{BASE}/search#{p['pid']}-{p['lang']}",
            title=p["title"].title() if p["title"].isupper() else p["title"],
            company=p["subtitle"], location="Avrupa (program)", job_type="Staj programı",
            deadline=deadline, description=(p["subtitle"] + "\n" + p["description"]).strip(),
            extra={"facts": p["facts"], "additional": p["additional"],
                   "eurodesk_url": f"{BASE}/search#{p['pid']}-{p['lang']}"},
        ))
    return jobs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Eurodesk staj programlarını requests + BeautifulSoup ile topla")
    ap.add_argument("--pages", type=int, default=config.EURODESK_MAX_PAGES)
    ap.add_argument("--browser", action="store_true", help="doğrudan Selenium (tarayıcı) yolunu kullan")
    a = ap.parse_args()
    save_jobs(scrape(a.pages, a.browser), "eurodesk")

"""
YÖNTEM 1: requests + Beautiful Soup  (statik sayfa scraping)
==========================================================
Kaynak: https://www.youthall.com/tr/is-ilanlari/  (öğrenci/yeni mezun iş ve staj ilanları)

Avrupa odağı: Youthall Türkiye merkezli bir site; Avrupa'daki ilanlar çok az. Bu yüzden
  liste sayfasındaki filtre formundan Türkiye DIŞINDAKİ şehir seçenekleri (ör. Münih,
  Amsterdam, Valencia) otomatik okunuyor ve yalnızca bu şehirlerdeki staj ilanları isteniyor:
  /tr/is-ilanlari/?city[]=302&city[]=2262&type[]=internship&type[]=mt_internship&page=N

Neden bu yöntem?
  Youthall sayfaları sunucu tarafında oluşturuluyor (server-side rendering): ilanlar
  HTML'in içinde hazır geliyor. Bu yüzden tarayıcı açmaya gerek yok; `requests` ile
  HTML'i indirip Beautiful Soup ile ayrıştırmak yeterli ve çok hızlı.

Akış:
  1) Liste sayfaları  (?page=1, 2, 3 ...)  -> her karttan başlık, şirket, tür, tarih, şehir, link
  2) Her ilanın detay sayfası -> sayfadaki JSON-LD (schema.org/JobPosting) verisinden açıklama
     + "Detaylar" kutusundaki Departman / Son Başvuru / Lokasyon alanları

robots.txt: liste ve ilan sayfaları genel tarayıcılara açık (Allow: /). Yine de istekler
arasında 1.5-3.5 sn bekliyoruz.

Çalıştırma:  python -m scrapers.youthall_bs4 --pages 3
"""
from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config
from scrapers.common import PARSER, Job, clean, country_iso, country_tr, html_to_text, polite_sleep, save_jobs

BASE = "https://www.youthall.com"
LIST_URL = BASE + "/tr/is-ilanlari/?page={page}"
STAJ_TURLERI = ("internship", "mt_internship")

TR_ILLER = {  # Türkiye'nin 81 ili: filtre formundaki şehirlerden bunları ayıklıyoruz
    "adana", "adıyaman", "afyonkarahisar", "ağrı", "amasya", "ankara", "antalya", "artvin", "aydın",
    "balıkesir", "bilecik", "bingöl", "bitlis", "bolu", "burdur", "bursa", "çanakkale", "çankırı",
    "çorum", "denizli", "diyarbakır", "edirne", "elazığ", "erzincan", "erzurum", "eskişehir",
    "gaziantep", "giresun", "gümüşhane", "hakkari", "hatay", "ısparta", "isparta", "mersin", "istanbul",
    "izmir", "kars", "kastamonu", "kayseri", "kırklareli", "kırşehir", "kocaeli", "konya", "kütahya",
    "malatya", "manisa", "kahramanmaraş", "mardin", "muğla", "muş", "nevşehir", "niğde", "ordu", "rize",
    "sakarya", "samsun", "siirt", "sinop", "sivas", "tekirdağ", "tokat", "trabzon", "tunceli",
    "şanlıurfa", "uşak", "van", "yozgat", "zonguldak", "aksaray", "bayburt", "karaman", "kırıkkale",
    "batman", "şırnak", "bartın", "ardahan", "ığdır", "yalova", "karabük", "kilis", "osmaniye", "düzce",
}


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def parse_city_options(html: str) -> list[tuple[str, str]]:
    """Filtre formundaki şehir seçeneklerini (değer, ad) olarak döndürür."""
    soup = BeautifulSoup(html, PARSER)
    out = []
    for inp in soup.select('input[name="city[]"]'):
        label = soup.select_one(f'label[for="{inp.get("id")}"]') if inp.get("id") else None
        name = clean((label or inp.parent).get_text())
        if inp.get("value"):
            out.append((inp["value"], name))
    return out


def foreign_cities(options: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(v, n) for v, n in options if tr_lower(n) not in TR_ILLER and n]


def build_europe_url(city_ids: list[str], page: int) -> str:
    q = "&".join([f"city%5B%5D={c}" for c in city_ids] + [f"type%5B%5D={t}" for t in STAJ_TURLERI])
    return f"{BASE}/tr/is-ilanlari/?{q}&page={page}"


# ---------------------------------------------------------------------------
# Ayrıştırma (parse) fonksiyonları — HTML metni alır, veri döndürür.
# İnternetten bağımsız oldukları için testlerde örnek HTML ile denenebilirler.
# ---------------------------------------------------------------------------
def parse_list_page(html: str) -> list[dict]:
    """Liste sayfasındaki ilan kartlarını çıkarır."""
    soup = BeautifulSoup(html, PARSER)
    items = []
    # Her kart: <div class="jobs"><a href="..."> ... <div class="jobs-content-title"><h5>Başlık</h5>
    for title_el in soup.select(".jobs-content-title h5"):
        a = title_el.find_parent("a")
        if not a or not a.get("href"):
            continue
        if "/yetenek-programlari/" in a["href"]:      # her sayfada çıkan yan reklam kutuları
            continue
        url = urljoin(BASE, a["href"])
        logo = a.select_one("img.jobs-content-logo")
        company = clean(logo.get("alt", "")) if logo else ""
        company = re.sub(r"\s+logo$", "", company, flags=re.I)

        # Etiketleri ikonlarına göre ayırıyoruz (sıra değişse de doğru alan bulunur)
        tags = {"type": "", "date": "", "location": "", "other": []}
        for tag in a.select(".jobs-tag"):
            icon = " ".join(tag.i.get("class", [])) if tag.i else ""
            text = clean(tag.get_text()).rstrip("+").strip()
            if "briefcase" in icon:
                tags["type"] = text
            elif "clock" in icon:
                tags["date"] = text
            elif "map-marker" in icon:
                tags["location"] = text
            elif text:
                tags["other"].append(text)

        desc_el = a.select_one(".jobs-content-desc")
        items.append({
            "url": url,
            "title": clean(title_el.get_text()),
            "company": company,
            "job_type": tags["type"],
            "deadline": tags["date"],
            "location": tags["location"] or ", ".join(tags["other"]),
            "short_desc": clean(desc_el.get_text()) if desc_el else "",
        })
    return items


def parse_detail_page(html: str) -> dict:
    """İlan detay sayfasından açıklama ve özellikleri çıkarır."""
    soup = BeautifulSoup(html, PARSER)
    out = {"description": "", "features": {}, "company": "", "title": "", "posted_date": ""}

    # 1) JSON-LD: arama motorları için gömülen yapılandırılmış veri (en güvenilir kaynak)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            out["description"] = html_to_text(data.get("description", ""))
            out["title"] = clean(data.get("title"))
            out["posted_date"] = clean(data.get("datePosted"))
            org = data.get("hiringOrganization") or {}
            out["company"] = clean(org.get("name") if isinstance(org, dict) else "")
            break

    # 2) Yedek: JSON-LD yoksa sayfadaki açıklama kutusu
    if not out["description"]:
        post = soup.select_one(".c-job_post_content")
        if post:
            out["description"] = html_to_text(str(post))

    # 3) "Detaylar" kutusu: <h6>Departman</h6><small>Yazılım</small> çiftleri
    for feat in soup.select(".c-job_detail_content_list_features"):
        key, val = feat.find("h6"), feat.find("small")
        if key and val:
            out["features"][clean(key.get_text())] = clean(val.get_text(" "))

    if not out["company"]:
        c = soup.select_one(".c-job_info_company")
        out["company"] = clean(c.get_text()) if c else ""
    return out


def job_id_from_url(url: str) -> str:
    # .../tr/LogoYazilim/log-in-winter-staj-programi_34/  ->  LogoYazilim/log-in-winter-staj-programi_34
    parts = [p for p in url.rstrip("/").split("/") if p]
    return "/".join(parts[-2:])


# ---------------------------------------------------------------------------
# İndirme (fetch) kısmı
# ---------------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"})
    return s


def fetch(session: requests.Session, url: str, retries: int = 3) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.text
            print(f"  ! HTTP {r.status_code}: {url} (deneme {attempt})")
            if r.status_code in (403, 404):
                return None
        except requests.RequestException as e:
            print(f"  ! Bağlantı hatası: {e} (deneme {attempt})")
        polite_sleep(3, 6)
    return None


def scrape(max_pages: int = config.YOUTHALL_MAX_PAGES, max_jobs: int | None = None) -> list[Job]:
    session = make_session()
    seen: dict[str, dict] = {}

    # 0) Filtre formundan Türkiye dışındaki şehirleri bul
    first = fetch(session, LIST_URL.format(page=1))
    cities = foreign_cities(parse_city_options(first or ""))
    if not cities:
        print("[youthall] Türkiye dışında şehir filtresi yok; Avrupa ilanı bulunamadı.")
        return []
    print(f"[youthall] yurt dışı şehirler: {', '.join(n for _, n in cities)}")
    city_ids = [v for v, _ in cities]

    # 1) Liste sayfaları (yalnızca bu şehirler + staj türleri)
    for page in range(1, max_pages + 1):
        polite_sleep()
        html = fetch(session, build_europe_url(city_ids, page))
        if not html:
            break
        cards = parse_list_page(html)
        new = [c for c in cards if c["url"] not in seen]
        print(f"[youthall] sayfa {page}: {len(cards)} kart, {len(new)} yeni")
        if not new:                       # yeni ilan gelmiyorsa son sayfaya ulaştık
            break
        for c in new:
            seen[c["url"]] = c
        polite_sleep()

    cards = list(seen.values())[: max_jobs or None]

    # 2) Detay sayfaları
    jobs: list[Job] = []
    for i, c in enumerate(cards, 1):
        polite_sleep()
        html = fetch(session, c["url"])
        d = parse_detail_page(html) if html else {"description": "", "features": {}}
        f = d.get("features", {})
        jobs.append(Job(
            source="youthall", method="requests+bs4",
            job_id=job_id_from_url(c["url"]), url=c["url"],
            title=d.get("title") or c["title"],
            company=d.get("company") or c["company"],
            location=f.get("Çalışma Lokasyonları") or c["location"],
            country=country_tr(country_iso(f.get("Çalışma Lokasyonları") or c["location"])),
            job_type=f.get("İlan Türü") or c["job_type"],
            work_model=f.get("Çalışma Şekli", ""),
            posted_date=f.get("Yayınlanma Tarihi") or d.get("posted_date", ""),
            deadline=f.get("Son Başvuru") or c["deadline"],
            department=f.get("Departman", ""),
            description=d.get("description") or c["short_desc"],
            extra={"features": f},
        ))
        print(f"[youthall] detay {i}/{len(cards)}: {jobs[-1].title[:60]}")
    return jobs


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Youthall ilanlarını requests + BeautifulSoup ile topla")
    ap.add_argument("--pages", type=int, default=config.YOUTHALL_MAX_PAGES)
    ap.add_argument("--max-jobs", type=int, default=None)
    args = ap.parse_args()
    save_jobs(scrape(args.pages, args.max_jobs), "youthall")

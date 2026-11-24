"""
YÖNTEM 3: Sitenin kendi JSON API'si  (requests ile "gizli API" kullanımı)
=======================================================================
Kaynak: EURES — Avrupa Komisyonu'nun resmi iş hareketliliği portalı
        https://europa.eu/eures/portal/jv-se/search

Nasıl bulundu?
  EURES arama sayfası bir JavaScript (Angular) uygulaması: HTML'de ilan yok. Bu yüzden ya
  Selenium ile sayfayı çizdirmek ya da sayfanın arka planda çağırdığı adresi bulmak gerekir.
  Tarayıcının Geliştirici Araçları > Network sekmesinde, sayfanın aramayı şu adrese
  POST isteğiyle yaptığı görüldü:
      https://europa.eu/eures/api/jv-searchengine/public/jv-search/search
  Bu adres ilanları (tam açıklama, ülke kodu, işveren, tarih) doğrudan JSON olarak veriyor.
  HTML ayrıştırmaya hiç gerek kalmıyor: en hızlı ve en sağlam yöntem.

robots.txt: europa.eu bu yolu yasaklamıyor ama "Crawl-delay: 10" istiyor -> istekler arası 10 sn.

Çalıştırma:  python -m scrapers.eures_api --max 25
"""
from __future__ import annotations

import argparse
import time
import uuid
from datetime import datetime, timezone

import requests

import config
from scrapers.common import Job, clean, country_tr, html_to_text, save_jobs

API_URL = "https://europa.eu/eures/api/jv-searchengine/public/jv-search/search"
DETAIL_URL = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=en"


def build_query(keyword: str, page: int = 1, per_page: int = 50, countries: list[str] | None = None) -> dict:
    """Sitenin kendi gönderdiği isteğin aynısı (Network sekmesinden alındı)."""
    return {
        "resultsPerPage": per_page, "page": page, "sortSearch": "MOST_RECENT",
        "keywords": [{"keyword": keyword, "specificSearchCode": "EVERYWHERE"}],
        "publicationPeriod": None, "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [],
        "positionScheduleCodes": [], "sectorCodes": [], "educationAndQualificationLevelCodes": [],
        "positionOfferingCodes": [], "locationCodes": [c.lower() for c in (countries or [])],
        "euresFlagCodes": [], "otherBenefitsCodes": [], "requiredLanguages": [],
        "minNumberPost": None, "sessionId": uuid.uuid4().hex[:16],
    }


def parse_results(data: dict, keyword: str = "") -> list[Job]:
    jobs = []
    for jv in data.get("jvs", []):
        isos = list((jv.get("locationMap") or {}).keys())
        iso = isos[0].upper() if isos else ""
        # Açıklama ilanın kendi dilinde; İngilizce çevirisi varsa onu al
        tr = (jv.get("translations") or {})
        en = tr.get("en") or {}
        desc_html = en.get("description") or jv.get("description") or ""
        title = en.get("title") or jv.get("title") or ""
        created = jv.get("creationDate")
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
                  if isinstance(created, (int, float)) else "")
        employer = (jv.get("employer") or {}).get("name") or ""
        jobs.append(Job(
            source="eures", method="json-api", job_id=str(jv.get("id")),
            url=DETAIL_URL.format(id=jv.get("id")), title=clean(title),
            company=clean(employer), location=country_tr(iso) or iso,
            country=country_tr(iso) or iso,
            job_type=", ".join(jv.get("positionScheduleCodes") or []),
            posted_date=posted, description=html_to_text(desc_html),
            extra={"iso": iso, "nuts": jv.get("locationMap"), "languages": jv.get("availableLanguages"), "eures_flag": jv.get("euresFlag"),
                   "offering": jv.get("positionOfferingCode"), "keywords": [keyword]},
        ))
    return jobs


def scrape(keywords=None, max_per_kw: int = config.EURES_MAX_PER_KEYWORD) -> list[Job]:
    keywords = keywords or config.EURES_KEYWORDS
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT, "Content-Type": "application/json",
                      "Accept": "application/json", "Origin": "https://europa.eu",
                      "Referer": "https://europa.eu/eures/portal/jv-se/search?lang=en"})
    out: dict[str, Job] = {}
    first = True
    for kw in keywords:
        got, new, total = 0, 0, None
        for page in range(1, (max_per_kw + 49) // 50 + 1):
            if not first:
                time.sleep(config.EURES_DELAY)            # robots.txt Crawl-delay
            first = False
            try:
                r = s.post(API_URL, json=build_query(kw, page=page, per_page=50), timeout=40)
            except requests.RequestException as e:
                print(f"  ! EURES bağlantı hatası: {e}")
                break
            if r.status_code != 200:
                print(f"  ! EURES HTTP {r.status_code} ('{kw}', sayfa {page})")
                break
            data = r.json()
            total = data.get("numberRecords")
            jobs = parse_results(data, kw)
            if not jobs:
                break
            for j in jobs[: max_per_kw - got]:
                if j.job_id in out:
                    out[j.job_id].extra["keywords"].append(kw)
                else:
                    out[j.job_id] = j
                    new += 1
            got += len(jobs)
            if got >= max_per_kw or got >= (total or 0):
                break
        print(f"[eures] '{kw}': toplam {total} kayıt, {min(got, max_per_kw)} alındı, {new} yeni")
    return list(out.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EURES staj ilanlarını resmi JSON API'den topla")
    ap.add_argument("--max", type=int, default=config.EURES_MAX_PER_KEYWORD)
    ap.add_argument("--keywords", nargs="*", default=None)
    a = ap.parse_args()
    save_jobs(scrape(a.keywords, a.max), "eures")

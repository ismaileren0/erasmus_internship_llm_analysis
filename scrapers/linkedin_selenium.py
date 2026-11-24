"""
YÖNTEM 2: Selenium  (dinamik sayfa scraping — gerçek tarayıcı otomasyonu)
=======================================================================
Kaynak: LinkedIn'in giriş yapmadan görülebilen herkese açık iş arama sayfası
        https://www.linkedin.com/jobs/search?keywords=Erasmus%20Internship&location=European%20Union&f_E=1
        (konum: Avrupa Birliği, f_E=1 = deneyim seviyesi "Staj")

Neden Selenium?
  Bu sayfa ilk açılışta yalnızca ~25-60 ilan gösteriyor. Devamı JavaScript ile, sayfayı
  aşağı kaydırdıkça ya da "Daha fazla iş ilanı göster" butonuna basınca yükleniyor.
  Ayrıca açılışta bir "oturum aç" penceresi (modal) çıkıyor. `requests` JavaScript
  çalıştıramadığı için bu ilanlara ulaşamaz; Selenium gerçek bir Chrome açıp
  kaydırma, tıklama ve bekleme işlemlerini bir insan gibi yapar.

Akış:
  1) Arama sayfasını aç -> giriş penceresini kapat
  2) Aşağı kaydır + "daha fazla" butonuna tıkla  (yeterli ilan yüklenene kadar)
  3) Yüklenen sayfanın HTML'ini Beautiful Soup ile ayrıştır (iki yöntemin birlikte kullanımı)
  4) Her ilanın sayfasına git, tam açıklamayı ve kriterleri (kıdem, istihdam türü) oku

Not: Selenium 4.6+ sürümü ChromeDriver'ı otomatik indirir (Selenium Manager).
     Bilgisayarda Google Chrome kurulu olması yeterli.
Etik: Sadece herkese açık sayfalar, kişisel veri yok, düşük hız (istek başı 2-5 sn).

Çalıştırma:  python -m scrapers.linkedin_selenium --max 30          (tarayıcıyı izleyerek)
             python -m scrapers.linkedin_selenium --max 30 --headless
"""
from __future__ import annotations

import argparse
import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (NoSuchElementException, TimeoutException,
                                        ElementNotInteractableException,
                                        ElementClickInterceptedException, WebDriverException)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config
from scrapers.common import PARSER, Job, clean, country_iso, country_tr, html_to_text, polite_sleep, save_jobs

SEARCH_URL = "https://www.linkedin.com/jobs/search?keywords={kw}&location={loc}&f_E=1"   # f_E=1: staj
JOB_URL = "https://www.linkedin.com/jobs/view/{id}/"

CARD_SEL = "ul.jobs-search__results-list > li"
MORE_BTN_SEL = "button.infinite-scroller__show-more-button"
MODAL_CLOSE_SEL = "button.modal__dismiss"
DESC_SEL = ".show-more-less-html__markup"


# ---------------------------------------------------------------------------
# Tarayıcı
# ---------------------------------------------------------------------------
def make_driver(headless: bool = False) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--lang=en-US")          # ülke adları İngilizce gelsin (ayrıştırma için)
    opts.add_argument(f"--user-agent={config.USER_AGENT}")
    opts.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en"})
    opts.add_argument("--disable-blink-features=AutomationControlled")  # "bot" izini azaltır
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # İsteğe bağlı: CHROMEDRIVER_PATH ortam değişkeniyle elle sürücü yolu verilebilir
    driver_path = os.getenv("CHROMEDRIVER_PATH")
    service = webdriver.ChromeService(executable_path=driver_path) if driver_path else None
    driver = webdriver.Chrome(options=opts, service=service)
    driver.set_page_load_timeout(40)
    return driver


def dismiss_modal(driver) -> None:
    """Açılışta çıkan 'oturum aç' penceresini kapatır (yoksa sessizce geçer)."""
    try:
        btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.CSS_SELECTOR, MODAL_CLOSE_SEL)))
        btn.click()
    except (TimeoutException, ElementNotInteractableException, ElementClickInterceptedException):
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except WebDriverException:
            pass


def load_more_cards(driver, target: int, max_rounds: int = 25) -> int:
    """Kaydır + 'daha fazla' butonuna bas; hedef sayıya ya da sona ulaşınca dur."""
    stale_rounds = 0
    count = len(driver.find_elements(By.CSS_SELECTOR, CARD_SEL))
    for _ in range(max_rounds):
        if count >= target:
            break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        polite_sleep(1.5, 2.5)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, MORE_BTN_SEL)
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)   # JS ile tıklama: üstte başka öğe olsa da çalışır
                polite_sleep(1.5, 2.5)
        except NoSuchElementException:
            pass
        new_count = len(driver.find_elements(By.CSS_SELECTOR, CARD_SEL))
        stale_rounds = stale_rounds + 1 if new_count == count else 0
        count = new_count
        print(f"  [linkedin] yüklenen kart: {count}")
        if stale_rounds >= 3:            # 3 tur boyunca yeni ilan gelmediyse liste bitti
            break
    return count


# ---------------------------------------------------------------------------
# Ayrıştırma — Selenium'un getirdiği HTML'i Beautiful Soup ile okuyoruz
# ---------------------------------------------------------------------------
def parse_search_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, PARSER)
    out = []
    for li in soup.select(CARD_SEL):
        card = li.select_one("[data-entity-urn]")
        urn = card.get("data-entity-urn", "") if card else ""
        m = re.search(r"(\d+)$", urn)
        link = li.select_one("a.base-card__full-link")
        if not m and link:
            m = re.search(r"-(\d+)(?:\?|$)", link.get("href", ""))
        if not m:
            continue
        t = li.select_one(".base-search-card__title")
        c = li.select_one(".base-search-card__subtitle")
        loc = li.select_one(".job-search-card__location")
        date = li.select_one("time")
        out.append({
            "job_id": m.group(1),
            "title": clean(t.get_text()) if t else "",
            "company": clean(c.get_text()) if c else "",
            "location": clean(loc.get_text()) if loc else "",
            "posted_date": date.get("datetime", "") if date else "",
        })
    return out


def parse_job_page(html: str) -> dict:
    soup = BeautifulSoup(html, PARSER)
    desc = soup.select_one(DESC_SEL)
    criteria = {}
    for item in soup.select(".description__job-criteria-item"):
        k, v = item.find("h3"), item.find("span")
        if k and v:
            criteria[clean(k.get_text())] = clean(v.get_text())
    title = soup.select_one(".top-card-layout__title, h1")
    return {
        "description": html_to_text(str(desc)) if desc else "",
        "criteria": criteria,
        "title": clean(title.get_text()) if title else "",
    }


def _crit(criteria: dict, *keys: str) -> str:
    for k in keys:
        if criteria.get(k):
            return criteria[k]
    return ""


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def _known_ids() -> set[str]:
    """Önceki çalıştırmalarda açıklaması zaten alınmış ilanlar (tekrar açılmaz -> zaman kazanılır)."""
    import json
    p = config.RAW_DIR / "linkedin.json"
    if not p.exists():
        return set()
    try:
        return {str(r["job_id"]) for r in json.loads(p.read_text(encoding="utf-8")) if r.get("description")}
    except (ValueError, KeyError):
        return set()


def scrape(keywords=None, location=None, max_per_kw: int = config.LINKEDIN_MAX_PER_KEYWORD,
           headless: bool = False, searches: list[tuple[str, str]] | None = None) -> list[Job]:
    if searches is None:
        if keywords or location:
            searches = [(k, location or config.LINKEDIN_LOCATION) for k in (keywords or config.LINKEDIN_KEYWORDS)]
        else:
            searches = config.LINKEDIN_SEARCHES
    known = _known_ids()
    driver = make_driver(headless)
    jobs: dict[str, Job] = {}
    try:
        for si, (kw, location) in enumerate(searches, 1):
            url = SEARCH_URL.format(kw=quote(kw), loc=quote(location))
            print(f"[linkedin] arama {si}/{len(searches)}: '{kw}' @ {location}")
            driver.get(url)
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, CARD_SEL)))
            except TimeoutException:
                print("  ! İlan listesi yüklenmedi (giriş duvarı / engel olabilir), atlanıyor.")
                continue
            dismiss_modal(driver)
            load_more_cards(driver, max_per_kw)

            cards = parse_search_results(driver.page_source)[:max_per_kw]
            print(f"  [linkedin] '{kw}': {len(cards)} kart ayrıştırıldı")

            for i, c in enumerate(cards, 1):
                if c["job_id"] in jobs:                    # başka bir aramada zaten alındı
                    jobs[c["job_id"]].extra["keywords"].append(kw)
                    continue
                if c["job_id"] in known:                   # önceki çalıştırmada alındı: detay sayfasını atla
                    continue
                polite_sleep(2, 5)
                job_url = JOB_URL.format(id=c["job_id"])
                detail = {"description": "", "criteria": {}}
                try:
                    driver.get(job_url)
                    if "authwall" in driver.current_url or "login" in driver.current_url:
                        print("  ! Giriş duvarına takıldı; biraz bekleyip devam ediliyor.")
                        polite_sleep(8, 15)
                    else:
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, DESC_SEL)))
                        detail = parse_job_page(driver.page_source)
                except (TimeoutException, WebDriverException) as e:
                    print(f"  ! Detay alınamadı ({type(e).__name__}): {job_url}")
                cr = detail.get("criteria", {})
                jobs[c["job_id"]] = Job(
                    source="linkedin", method="selenium",
                    job_id=c["job_id"], url=job_url,
                    title=c["title"] or detail.get("title", ""),
                    company=c["company"], location=c["location"],
                    country=country_tr(country_iso(c["location"])),
                    job_type=_crit(cr, "İstihdam türü", "Employment type"),
                    posted_date=c["posted_date"],
                    department=_crit(cr, "İş fonksiyonu", "Job function"),
                    description=detail.get("description", ""),
                    extra={"criteria": cr, "keywords": [kw],
                           "seniority": _crit(cr, "Kıdem düzeyi", "Seniority level"),
                           "industry": _crit(cr, "Sektörler", "Industries")},
                )
                print(f"  [linkedin] detay {i}/{len(cards)}: {c['title'][:60]}")
                if len(jobs) % 25 == 0:                    # ara kayıt: uzun çalışma yarıda kesilirse kaybolmasın
                    save_jobs(list(jobs.values()), "linkedin")
    finally:
        driver.quit()
    return list(jobs.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="LinkedIn herkese açık ilanlarını Selenium ile topla")
    ap.add_argument("--max", type=int, default=config.LINKEDIN_MAX_PER_KEYWORD, help="arama başına en fazla ilan")
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--headless", action="store_true", help="tarayıcı penceresi açmadan çalış")
    args = ap.parse_args()
    save_jobs(scrape(args.keywords, max_per_kw=args.max, headless=args.headless), "linkedin")

"""
Tüm boru hattını (pipeline) sırayla çalıştırır — Avrupa'daki staj ilanları:
  0) Üniversiteler -> Wikidata SPARQL açık veri (Polonya vb.; spekülatif başvuru hedefleri)
  1) Eurodesk  -> requests + BeautifulSoup   (AB staj programları)
  2) EURES     -> requests + resmi JSON API  (Avrupa Komisyonu iş portalı)
  3) LinkedIn  -> Selenium                   (konum: Avrupa Birliği, filtre: staj)
  4) Youthall  -> requests + BeautifulSoup   (yalnızca Türkiye dışı şehirler)
  5) Temizleme -> pandas + SQLite
  6) LLM analizi -> Ollama
  7) İstatistik + grafikler + LLM piyasa özeti

Örnekler:
  python run_all.py                       # hepsi
  python run_all.py --quick               # hızlı deneme (az ilan)
  python run_all.py --skip-scrape         # veriler zaten varsa sadece analiz
  python run_all.py --only eures eurodesk # yalnızca seçilen kaynaklar
  python run_all.py --headless            # Selenium penceresiz
  python run_all.py --daily               # GÜNLÜK: yeni ilanları topla, yalnızca yenileri LLM'e gönder
"""
import argparse
import shutil
import time
from datetime import datetime

import config
from scrapers import eurodesk_bs4, eures_api, linkedin_selenium, universities_wikidata, youthall_bs4
from scrapers.common import save_jobs
from pipeline import clean, llm_analyze, stats

SOURCES = ("universiteler", "eurodesk", "eures", "youthall", "linkedin")   # en uzun süren (LinkedIn) en sonda


def run_source(name: str, quick: bool, headless: bool) -> None:
    print(f"\n=== {name} ===")
    try:
        if name == "universiteler":
            universities_wikidata.scrape()
            return
        if name == "eurodesk":
            jobs = eurodesk_bs4.scrape(max_pages=1 if quick else config.EURODESK_MAX_PAGES)
        elif name == "eures":
            jobs = eures_api.scrape(keywords=["internship"] if quick else None,
                                    max_per_kw=10 if quick else config.EURES_MAX_PER_KEYWORD)
        elif name == "linkedin":
            jobs = linkedin_selenium.scrape(searches=[("Erasmus Internship", "European Union")] if quick else None,
                                            max_per_kw=5 if quick else config.LINKEDIN_MAX_PER_KEYWORD,
                                            headless=headless)
        else:
            jobs = youthall_bs4.scrape(max_pages=1 if quick else config.YOUTHALL_MAX_PAGES)
        save_jobs(jobs, name)
    except Exception as e:  # noqa: BLE001  — bir kaynak çökerse diğerleriyle devam et
        print(f"! {name} adımı başarısız: {e}\n  (diğer kaynaklarla devam ediliyor)")


def backup_previous() -> None:
    """Önceki sonuçları data/yedek/<tarih-saat>/ altına kopyalar (sunumdaki sayılar kaybolmasın)."""
    src = config.DATA_DIR / "analiz.csv"
    if not src.exists():
        return
    dst = config.DATA_DIR / "yedek" / datetime.now().strftime("%Y%m%d-%H%M")
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst / "analiz.csv")
    if config.OUT_DIR.exists():
        shutil.copytree(config.OUT_DIR, dst / "outputs", dirs_exist_ok=True)
    print(f"[yedek] önceki sonuçlar kopyalandı -> {dst}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--only", nargs="*", choices=SOURCES, default=None)
    ap.add_argument("--quick", action="store_true", help="az veriyle hızlı deneme")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--daily", action="store_true",
                    help="günlük mod: Youthall'ı ve LLM piyasa özetini atla (daha hızlı)")
    ap.add_argument("--no-summary", action="store_true", help="LLM piyasa özetini yazdırma")
    a = ap.parse_args()
    if a.daily and not a.only:
        a.only = ["eurodesk", "eures", "linkedin"]   # üniversite listesi günlük değişmez
    backup_previous()
    if a.model:
        config.OLLAMA_MODEL = a.model

    t0 = time.time()
    if not a.skip_scrape:
        for name in a.only or SOURCES:
            run_source(name, a.quick, a.headless)

    print("\n=== Temizleme (pandas + SQLite) ===")
    clean.save(clean.build())
    print("\n=== LLM analizi (Ollama) ===")
    llm_analyze.run(limit=15 if a.quick else None, model=a.model)
    print("\n=== İstatistik + grafikler + piyasa özeti ===")
    stats.run(summary=not (a.daily or a.no_summary))
    print(f"\nBitti ({(time.time() - t0) / 60:.1f} dk). Paneli açmak için:  streamlit run app.py")


if __name__ == "__main__":
    main()

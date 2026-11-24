# Erasmus+ Staj Bulucu: Web Scraping ve LLM Analizi

[English](README.md) · **Türkçe**

*Yapay Zekaya Giriş* dersi vize projesi olarak, kendi Erasmus+ staj aramam için geliştirdiğim bir araç. Avrupa'daki staj ilanlarını üç farklı web scraping yöntemiyle toplar, her ilanı **yerel bir LLM (Ollama)** ile analiz eder ve sonuçları bir Streamlit panelinde CV'me uygunluğa göre sıralar.

```
 Eurodesk ──(requests + BeautifulSoup)──┐
 EURES    ──(gizli JSON API)────────────┤
 LinkedIn ──(Selenium + BeautifulSoup)──┼─> pandas + SQLite ─> Ollama LLM ─> dayanak kontrolü ─> istatistik + Streamlit
 Youthall ──(requests + BeautifulSoup)──┘
 Üniversiteler (Polonya) ──(Wikidata SPARQL)
```

## Sonuçlar (443 ilan)

| | |
|---|---|
| Analiz edilen ilan | 443 (LinkedIn 314, EURES 70, Eurodesk 59) |
| En çok ilan | Polonya 91, Fransa 83, Hollanda 60 |
| Erasmus+ uygun / muhtemelen uygun | 35 / 353 |
| İngilizcenin yeterli olduğu ilanlar | %91 |
| En çok istenen beceriler | Python (186), SQL (92), Yapay zeka/LLM (65) |
| Ortanca aylık ücret (ücret yazan 51 ilan) | 1.400 € |
| LLM ile anahtar kelime yöntemi, Jaccard benzerliği | 0,47 |
| **Dayanak kontrolünün yakaladığı uydurma beceri** | **2.168'de 326 (%15)** |

En önemli bulgu: LLM, yasaklayan açık bir talimata rağmen ilan metninde hiç geçmeyen beceriler yazdı (en çok SQL ve Python). Dayanak kontrolü (`pipeline/skills.py`) çıkarılan her beceriyi farklı yazımlarıyla birlikte ilan metninde arar ve bulamadıklarını sonuçtan çıkarır.

## Scraping yöntemleri

| Kaynak | Yöntem | Neden |
|---|---|---|
| [Eurodesk](https://programmes.eurodesk.eu/internships) | requests + Beautiful Soup | Programlar, JSON cevabın içinde hazır HTML olarak geliyor |
| [EURES](https://europa.eu/eures/portal/jv-se/search) | Gizli JSON API | Sayfa bir JavaScript uygulaması; arama API'si tarayıcının Network sekmesinden bulundu |
| [LinkedIn](https://www.linkedin.com/jobs/) | Selenium | İlanlar kaydırdıkça yükleniyor ve bir giriş penceresi çıkıyor |
| [Youthall](https://www.youthall.com/) | requests + Beautiful Soup | Sayfalar sunucuda hazır; Türkiye dışındaki şehirlerle filtrelendi |
| Üniversiteler | Wikidata SPARQL | Açık veri; EURAXESS robots.txt izin vermediği için kullanılmadı |

## LLM teknikleri

- **Structured output:** Ollama'ya bir Pydantic şeması verilir; model yalnızca bu JSON yapısında cevap verebilir, geçersiz cevaplar en fazla 3 kez yeniden istenir.
- **Tekrarlanabilirlik:** `temperature = 0` ve önbellek; her ilan bir kez analiz edilir.
- **LLM + kural:** Kesin kararlar kurala bağlıdır. Ülke Erasmus+ programında değilse (ör. İsviçre), model ne derse desin ilan uygun değil sayılır.
- **Değerlendirme:** LLM'in bulduğu beceriler elle yazılmış bir anahtar kelime sözlüğüyle karşılaştırılır (ilan başına beceri, Jaccard benzerliği, yalnızca LLM'in bulduğu beceriler).

## Panel

`streamlit run app.py` şu sekmeleri açar: Genel Bakış · Bugünün Listesi (CV'ye uyum puanı, 0–100) · Üniversiteler (e-posta taslaklarıyla) · Başvuru Listesi · Beceriler · LLM vs Klasik Yöntem · Motivasyon Mektubu · Canlı LLM Demo · Piyasa Özeti.

## Kurulum

Gerekenler: Python 3.10+, Google Chrome ve [Ollama](https://ollama.com/download).

```bash
python -m venv venv
venv\Scripts\activate              # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:7b             # ~4,7 GB; zayıf bilgisayarlar için: llama3.2:3b
```

Kendi alanın için `config.py` içinde `LINKEDIN_SEARCHES`, `MY_SKILLS`, `AVAILABILITY` ve `APPLICANT_PROFILE` ayarlarını değiştir.

## Kullanım

```bash
python run_all.py --quick          # az ilanla hızlı deneme
python run_all.py                  # tam çalıştırma (süre çoğunlukla LLM, ilan başına ~46 sn)
streamlit run app.py               # panel
python -m pytest -q                # internetsiz testler
```

Seçenekler: `--only eures eurodesk` · `--skip-scrape` · `--headless` · `--model llama3.2:3b` · `--daily` · `--no-summary`. Yarıda kesilen LLM analizi önbellekten devam eder.

## Proje yapısı

| Yol | Görevi |
|---|---|
| `config.py` | Tüm ayarlar: aramalar, bekleme süreleri, model, profil |
| `scrapers/` | Her kaynak için bir modül + ortak `Job` modeli ve Erasmus+ ülke listesi |
| `pipeline/clean.py` | Birleştirme, tekrarları silme, ülke normalizasyonu, SQLite |
| `pipeline/llm_analyze.py` | Ollama structured output, doğrulama, önbellek, mektuplar |
| `pipeline/skills.py` | Beceri sözlüğü, anahtar kelime yöntemi ve `grounded()` kontrolü |
| `pipeline/match.py` | CV uyum puanı |
| `pipeline/stats.py` | İstatistikler, grafikler, LLM ve klasik yöntem karşılaştırması |
| `app.py` | Streamlit paneli |
| `tests/` | Kayıtlı HTML/JSON örnekleriyle internetsiz testler |

## Etik

- Yalnızca giriş gerektirmeyen, herkese açık ilanlar toplanır; kişisel veri toplanmaz.
- robots.txt kurallarına uyulur; EURES istekleri arasında 10 sn beklenir (`Crawl-delay: 10`), LinkedIn istekleri yavaşlatılır ve eğitim amaçlı küçük ölçekte tutulur.
- İnsan doğrulaması isteyen (Erasmus Intern, Cloudflare) ya da robots.txt ile izin vermeyen siteler aşılmaya çalışılmadı, kapsam dışı bırakıldı.
- Buradaki Erasmus+ uygunluğu yalnızca bir ön elemedir; son kararı üniversitenin Erasmus ofisi verir.

## Geliştirici

İsmail Eren Uruç · Bilgisayar Mühendisliği, Burdur Mehmet Akif Ersoy Üniversitesi · [LinkedIn](https://www.linkedin.com/in/ismail-eren-uruc/) · [GitHub](https://github.com/ismaileren0)

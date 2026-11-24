# Web Scraping ve Büyük Dil Modelleri ile Avrupa Staj İlanı Analizi

**Yapay Zekaya Giriş, vize projesi.** Avrupa'daki staj ilanları dört kaynaktan, üç farklı web scraping yöntemiyle toplanır:

- **requests + Beautiful Soup:** Eurodesk ve Youthall
- **Sitenin kendi JSON API'si:** EURES
- **Selenium:** LinkedIn

Toplanan ilanlar yerel bir büyük dil modeliyle (**Ollama**, `qwen2.5:7b`) analiz edilir. Her ilandan şu bilgiler JSON olarak çıkarılır:

- **Erasmus+ stajına uygunluk** ve gerekçesi
- ülke, ücret ve süre
- zorunlu yerel dil şartı
- istenen beceriler

Panelde kişisel bir **başvuru listesi** hazırlanabilir. LLM, seçilen ilan için Erasmus+ vurgulu bir **motivasyon mektubu taslağı** da yazar.

```
 Eurodesk ──(requests + BeautifulSoup)──┐
 EURES    ──(requests + JSON API)───────┤
 LinkedIn ──(Selenium + BeautifulSoup)──┼─> data/raw/*.json ─> pandas + SQLite ─> Ollama LLM ─> grafikler + Streamlit + özet
 Youthall ──(requests + BeautifulSoup)──┘
```

| Kaynak | Ne var | Yöntem | Neden bu yöntem |
|---|---|---|---|
| [Eurodesk Opportunity Finder](https://programmes.eurodesk.eu/internships) | AB kurumlarının ve uluslararası kuruluşların staj programları (ECB, Eurojust, Digital Opportunity Traineeships…) | requests + BS4 | Veri, JSON içinde hazır HTML olarak geliyor; tarayıcıya gerek yok |
| [EURES](https://europa.eu/eures/portal/jv-se/search) | Avrupa Komisyonu'nun resmi iş portalı; tüm AB ülkelerinden gerçek şirket stajları | requests + JSON API | Sayfa JavaScript uygulaması. Arka planda çağırdığı API, Network sekmesinden bulundu |
| [LinkedIn](https://www.linkedin.com/jobs/search?keywords=Erasmus%20Internship&location=European%20Union&f_E=1) | Konum Avrupa Birliği, deneyim seviyesi "Staj" | Selenium | İlanlar kaydırdıkça yükleniyor ve açılışta giriş penceresi çıkıyor |
| [Youthall](https://www.youthall.com/tr/is-ilanlari/) | Yalnızca Türkiye dışı şehir filtresindeki staj ilanları | requests + BS4 | Sayfalar sunucuda hazır geliyor. Avrupa ilanı çok az, bu da bir bulgu |

## Kurulum (bir kerelik)

1. **Python 3.10+** ve **Google Chrome** kurulu olmalı.
2. Proje klasöründe terminal açın:
   ```bash
   python -m venv venv
   venv\Scripts\activate            # Windows   (Mac/Linux: source venv/bin/activate)
   pip install -r requirements.txt
   ```
3. **Ollama** kurun: https://ollama.com/download , sonra modeli indirin:
   ```bash
   ollama pull qwen2.5:7b           # ~4.7 GB, çok dilli (Almanca/Fransızca ilanları da okur), en az 8 GB RAM
   # bilgisayar zayıfsa:  ollama pull llama3.2:3b   ve çalıştırırken --model llama3.2:3b
   ```
4. **Kendi alanına göre ayarla:** `config.py` içinde `LINKEDIN_KEYWORDS` (ör. `"Marketing Intern"`) ve `APPLICANT_PROFILE` (mektup için kısa tanıtımın).

## Çalıştırma

```bash
python run_all.py --quick        # 1) Hızlı deneme: az ilanla tüm adımlar (~5-10 dk)
python run_all.py                # 2) Asıl çalıştırma (~1-2 saat, çoğu LLM süresi)
streamlit run app.py             # 3) Panel tarayıcıda açılır
```

Adımlar tek tek de çalıştırılabilir:

| Adım | Komut | Çıktı |
|---|---|---|
| Eurodesk | `python -m scrapers.eurodesk_bs4` | `data/raw/eurodesk.json` |
| EURES | `python -m scrapers.eures_api --max 25` | `data/raw/eures.json` |
| LinkedIn | `python -m scrapers.linkedin_selenium --max 25` | `data/raw/linkedin.json` |
| Youthall | `python -m scrapers.youthall_bs4` | `data/raw/youthall.json` |
| Temizleme | `python -m pipeline.clean` | `data/ilanlar.db`, `data/ilanlar_temiz.csv` |
| LLM analizi | `python -m pipeline.llm_analyze` | `data/analiz.csv` |
| İstatistik ve özet | `python -m pipeline.stats` | `outputs/figures/*.png`, `outputs/pazar_ozeti.md` |
| Testler | `python -m pytest -q` | internetsiz ayrıştırıcı ve Selenium testleri |

**Seçenekler:**

- `--only eures eurodesk`: yalnızca seçilen kaynaklar
- `--skip-scrape`: veri varsa yalnızca analiz
- `--headless`: Selenium pencere açmaz
- `--model llama3.2:3b`: başka bir model

LLM analizi yarıda kesilirse aynı komutu tekrar çalıştırın; önbellekten devam eder.

## Üniversiteler (spekülatif başvuru)

`python -m scrapers.universities_wikidata` komutu Wikidata'nın açık SPARQL servisinden `config.UNIVERSITY_COUNTRIES` içindeki ülkelerin üniversitelerini çeker. Varsayılan ülke Polonya. Panelin **Üniversiteler** sekmesinde her üniversite için şunlar var:

- web sitesi
- Erasmus ofisini ve bilgisayar bölümünü aramak için hazır bağlantılar
- LLM ile yazılan bir e-posta taslağı

EURAXESS da denendi, ama robots.txt ilan sayfalarını ve parametreli aramaları yasakladığı için kullanılmadı.

## Halüsinasyon (dayanak) kontrolü

LLM bazen ilan metninde hiç geçmeyen becerileri yazıyor; örneğin bir perakende stajına "SQL". `pipeline/skills.py` içindeki `grounded()` fonksiyonu, LLM'in yazdığı her becerinin metinde gerçekten geçip geçmediğini kontrol eder. Geçmeyenler `dayanaksiz_beceriler` sütununa ayrılır ve analizden çıkarılır.

## Günlük başvuru akışı (Erasmus+ başvuru dönemi için)

Her sabah tek komut:

```bash
python run_all.py --daily
streamlit run app.py          # "Bugünün Listesi" sekmesi
```

- **Biriktirme:** Ham veriler `data/raw/*.json` dosyalarında birikir. Her ilanın ilk görüldüğü gün (`first_seen`) saklanır.
- **Yalnızca yeni ilanlar:** LLM yalnızca daha önce analiz edilmemiş ilanları işler, önbellek sayesinde.
- **Ön filtre (`config.PREFILTER`):** LLM'e yalnızca başlığı yazılım, veri veya yapay zeka alanında olan (`FIELD_TITLE_PATTERN`) ve metni İngilizce olan ilanlar gider. Bu, analiz süresini büyük ölçüde kısaltır.
- **Uyum puanı (`pipeline/match.py`, 0-100):** Erasmus+ uygunluğu 30, Haziran 2027 dönem uyumu 20, İngilizcenin yeterli olması 15, CV becerileriyle eşleşme 25 (`config.MY_SKILLS`), seviye 10 puan.
- **Bugünün Listesi:** En yüksek puanlı 20 ilan gösterilir. Durumu "Başvurdum" ya da "İlgilenmiyorum" yapılan ilanlar sonraki günlerde listeden çıkar. Kayıtlar `data/basvurular.csv` dosyasında tutulur.
- **Yedek:** Her çalıştırma, önceki sonuçları `data/yedek/<tarih-saat>/` altına kopyalar. Sunumdaki sayılar kaybolmaz.

## Panel sekmeleri

- **Genel Bakış:** ülke, Erasmus+ uygunluğu, ücret, kategori ve zorunlu dil şartı.
- **Başvuru Listesi:** filtrelenmiş ilanlar. İstediklerini seçip `basvuru_listem.csv` olarak indirebilirsin.
- **Beceriler:** en çok istenen beceriler. **LLM vs Klasik Yöntem** sekmesi, LLM'i anahtar kelime sözlüğüyle karşılaştırır.
- **Motivasyon Mektubu:** seçilen ilan için İngilizce taslak. İlk paragrafta "Erasmus+ kapsamında, ücret beklentisi yok, hibe AB'den" bilgisi yer alır.
- **Canlı LLM Demo:** herhangi bir dildeki ilan metnini yapıştırıp anlık analiz.
- **Piyasa Özeti:** LLM'in istatistiklerden yazdığı özet.

## Erasmus+ uygunluğu nasıl belirleniyor?

1. **LLM** ilanı okur ve `Uygun`, `Muhtemelen uygun` ya da `Uygun değil` der, yanına gerekçesini yazar. Kriterler: öğrencilere açık bir staj mı, süre, deneyim şartı.
2. **Ülke kuralı** bunun üstüne uygulanır. Erasmus+ Programme Guide 2026'ya göre uygun ülkeler AB'nin 27 üyesi ile İzlanda, Lihtenştayn, Norveç, Kuzey Makedonya, Sırbistan ve Türkiye'dir. Türkiye'den giden öğrenci için Türkiye sayılmaz. İsviçre uygun değildir; Birleşik Krallık 2027'den itibaren programa katılacak.

Bu bir **ön eleme**dir. Son kararı üniversitenin Erasmus ofisi verir.

## Dosyalar

| Dosya | Görevi |
|---|---|
| `config.py` | Tüm ayarlar: anahtar kelimeler, sayfa sayıları, model, bekleme süreleri, başvuru profili |
| `scrapers/eurodesk_bs4.py` | **requests + BS4:** JSON içindeki HTML'den `<template>` bloklarını ayrıştırma |
| `scrapers/eures_api.py` | **JSON API:** EURES'in arama API'sine POST isteği |
| `scrapers/linkedin_selenium.py` | **Selenium:** modal kapatma, kaydırma, "daha fazla" butonu, detay sayfaları |
| `scrapers/youthall_bs4.py` | **requests + BS4:** filtre formundan Türkiye dışı şehirleri bulma, JSON-LD okuma |
| `scrapers/common.py` | Ortak `Job` modeli, ülke tanıma ve Erasmus+ ülke listesi |
| `pipeline/clean.py` | pandas ile birleştirme, tekrarları silme, ülke normalizasyonu, SQLite |
| `pipeline/llm_analyze.py` | Ollama ile structured output (JSON şema) ve Pydantic doğrulama, önbellek, motivasyon mektubu |
| `pipeline/skills.py` | Beceri sözlüğü: normalleştirme ve klasik anahtar kelime yöntemi |
| `pipeline/stats.py` | İstatistikler, grafikler, LLM ve klasik yöntem karşılaştırması, LLM piyasa özeti |
| `app.py` | Streamlit paneli |
| `tests/` | Örnek HTML/JSON dosyalarıyla internetsiz testler |

## Sorun giderme

- **`Ollama'ya bağlanılamadı`:** Ollama uygulamasını açın veya `ollama serve` çalıştırın.
- **EURES `HTTP 403/400`:** Site API'sini değiştirmiş olabilir. Tarayıcıda EURES aramasını açın, F12 > Network'te `jv-search/search` isteğinin gövdesini kontrol edip `build_query()` ile karşılaştırın.
- **Eurodesk JSON yerine HTML döndürüyor:** Bot koruması devreye girmiş olabilir. Birkaç dakika sonra tekrar deneyin.
- **LinkedIn 0 ilan döndürüyor veya giriş duvarı çıkıyor:** 10-15 dk bekleyin, `--max` değerini düşürün ya da `--only eures eurodesk youthall` ile devam edin.
- **Youthall 0 ilan döndürüyor:** Normal. Youthall Türkiye odaklı bir site; Avrupa'da ilanı çok az.

## Etik ve yasal notlar

- Yalnızca giriş gerektirmeyen, herkese açık ilanlar toplanır; kişisel veri toplanmaz.
- **robots.txt:**
  - Eurodesk tüm siteye izin veriyor.
  - europa.eu (EURES) bu yolu yasaklamıyor ama `Crawl-delay: 10` istiyor; aramalar arası 10 sn beklenir.
  - Youthall ilan sayfalarına izin veriyor.
  - LinkedIn'in kullanım koşulları otomatik toplamayı kısıtladığı için o kısım küçük ölçekte, yalnızca eğitim amaçlı tutuldu.
- **Kapsam dışı bırakılan kaynaklar** (staj rehberinde önerilenlerden):
  - **Erasmus Intern:** Cloudflare insan doğrulaması istiyor; bu doğrulamayı aşmak etik değil.
  - **Globalplacement:** denemede robots.txt otomatik erişime izin vermedi.
  - **GoAbroad:** şirket stajları değil, ücretli aracı kurum programları listeliyor.

  Bu siteler tarayıcıdan elle kullanılabilir.

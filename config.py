"""
Proje genel ayarları.
Tüm yollar ve varsayılan değerler burada; diğer dosyalar buradan okur.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"           # scraper'ların ham çıktıları (JSON)
OUT_DIR = ROOT / "outputs"
FIG_DIR = OUT_DIR / "figures"
DB_PATH = DATA_DIR / "ilanlar.db"    # SQLite veritabanı

for _d in (DATA_DIR, RAW_DIR, OUT_DIR, FIG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Scraping ---------------------------------------------------------------
# Siteye kendimizi gerçek bir tarayıcı gibi tanıtıyoruz ve istekler arasında bekliyoruz
# (sunucuyu yormamak = etik scraping).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MIN_DELAY, MAX_DELAY = 1.5, 3.5      # saniye; her istekten önce rastgele bekleme

# Proje odağı: Avrupa'daki staj ilanları (Erasmus+ stajı başvurusu için)

# 1) Eurodesk Opportunity Finder (requests + BeautifulSoup) — AB kurumları ve uluslararası staj programları
EURODESK_MAX_PAGES = 5               # sayfa başına ~20 program

# 2) EURES — Avrupa Komisyonu'nun resmi iş portalı (requests + herkese açık JSON API)
EURES_KEYWORDS = [                   # farklı dillerde "staj" kelimesi
    "internship", "trainee", "Praktikum", "stagiaire", "prácticas", "tirocinio", "stagiair",
]
EURES_MAX_PER_KEYWORD = 150          # 3 sayfa x 50 ilan (alan filtresi sonra eler)
EURES_DELAY = 10                     # europa.eu robots.txt: Crawl-delay 10 sn

# 3) LinkedIn (Selenium) — konum: Avrupa Birliği, deneyim filtresi: Staj (f_E=1)
LINKEDIN_KEYWORDS = [                # CV'ye göre: backend + yapay zeka/veri odaklı roller
    "Erasmus Internship",
    "Summer Internship 2027 Software",
    "Software Engineering Intern",
    "Software Developer Intern",
    "Backend Developer Intern",
    "Python Developer Intern",
    "Full Stack Developer Intern",
    "Web Developer Intern",
    "Frontend Developer Intern",
    "AI Intern",
    "Machine Learning Intern",
    "Data Science Intern",
    "Data Engineer Intern",
    "Data Analyst Intern",
    "Computer Vision Intern",
    "Generative AI Intern",
]
LINKEDIN_LOCATION = "European Union"
LINKEDIN_MAX_PER_KEYWORD = 50        # her arama için en fazla ilan
# Üniversite ve araştırma kurumlarının ilanları için ek aramalar
LINKEDIN_RESEARCH_KEYWORDS = ["Research Intern", "Student Research Assistant", "Research Assistant Computer Science"]
# Polonya'ya özel aramalar (Kraków, Varşova, Wrocław'da İngilizce yazılım stajı çok)
LINKEDIN_POLAND_KEYWORDS = ["Software Engineering Intern", "Python Intern", "Backend Intern", "Data Science Intern",
                            "Machine Learning Intern", "AI Intern", "IT Intern", "Research Intern"]
# Tüm aramalar: (anahtar kelime, konum)
LINKEDIN_SEARCHES = ([(k, LINKEDIN_LOCATION) for k in LINKEDIN_KEYWORDS + LINKEDIN_RESEARCH_KEYWORDS]
                     + [(k, "Poland") for k in LINKEDIN_POLAND_KEYWORDS])

# 5) Üniversiteler (Wikidata SPARQL açık veri) — spekülatif staj başvurusu hedefleri
UNIVERSITY_COUNTRIES = ["PL"]        # ör. ["PL", "CZ", "HU", "PT", "LT"] — ISO kodları

# 4) Youthall (requests + BeautifulSoup) — yalnızca Türkiye dışındaki şehir filtreleri + staj türü
YOUTHALL_MAX_PAGES = 3

# --- LLM (Ollama) -----------------------------------------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")   # alternatif: llama3.1:8b, gemma3:4b, llama3.2:3b
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")          # "mock" sadece Ollama'sız test için
MAX_DESC_CHARS = 3000                # LLM'e gönderilen ilan metninin üst sınırı (hız için)

# --- Ön filtre: LLM'e yalnızca sana uygun olabilecek ilanları gönder (süreyi kısaltır) ---------
PREFILTER = True                     # False: tüm ilanlar analiz edilir (çok uzun sürer)
ONLY_ENGLISH = True                  # İlan metni İngilizce değilse LLM'e gönderme (yerel dil şartı olasılığı yüksek)
# Başlıkta bu kalıplardan biri geçmeli (yazılım / veri / yapay zeka; birkaç dilde). Eurodesk programları hariç tutulmaz.
FIELD_TITLE_PATTERN = (
    r"software|developer|develop|engineer|backend|back-end|frontend|front-end|full[ -]?stack|\bweb\b|"
    r"python|java\b|javascript|typescript|\.net|c\+\+|devops|cloud|platform|\bdata\b|daten|données|datos|\bdati\b|"
    r"machine learning|\bml\b|\bai\b|\bki\b|\bia\b|artificial intelligence|intelligence artificielle|"
    r"künstliche intelligenz|computer vision|\bnlp\b|\bllm|genai|generative|deep learning|\bit\b|"
    r"informati|programm|entwickl|développe|desarroll|sviluppat|ontwikkel|cyber|security|\bqa\b|automation|"
    r"analytics|analyst|business intelligence|\bbi\b|mobile|\bios\b|android|flutter|\bgame|3d|graphics|"
    r"robotic|embedded|it-|tech"
)

# --- Aday profili (CV'den; kişisel iletişim bilgisi yok) ----------------------------
AVAILABILITY = "Haziran 2027'den itibaren 2-6 ay (Erasmus+ stajı)"
MY_SKILLS = [                        # ilan becerileriyle eşleştirme (uygunluk puanı) için
    "Python", "JavaScript", "C/C++", "HTML/CSS", "REST API", "Django/Flask", "FastAPI", "Veri Analizi",
    "Makine Öğrenmesi", "Yapay Zeka / LLM", "Git", "Selenium", "Web Scraping", "Streamlit", "Three.js",
    "Flutter", "Dart", "Pandas", "NumPy", "scikit-learn", "Computer Vision", "GIS",
]
# Motivasyon mektubu taslağı için (panelde düzenlenebilir)
APPLICANT_PROFILE = os.getenv("APPLICANT_PROFILE", (
    "Third-year Computer Engineering student at Burdur Mehmet Akif Ersoy University (Türkiye), English B2. "
    "Seeking a backend development or AI internship. Skills: Python, JavaScript, REST APIs (OAuth2, retries), "
    "Flask, FastAPI, Pandas, NumPy, scikit-learn, Gemini API, Selenium, BeautifulSoup, Streamlit, Three.js, Git. "
    "Projects: Antalya Wildfire Risk Analysis (Python data pipeline merging Sentinel-2, Open-Meteo and NASA FIRMS "
    "APIs into 143,598 records; Random Forest AUC 0.82 vs 0.68 baseline; Streamlit dashboard); MERISO, a 3D space "
    "archaeology web atlas (Three.js, GLSL) that reached the Top 5 at NASA Space Apps Antalya 2026 as project lead; "
    "MedTRACK, a Gemini API-powered medication tracking web app (6th place in a one-week competition); a Selenium/"
    "BeautifulSoup price tracking bot and a freelance web scraping tool delivered on Fiverr. "
    "Available for a 2-6 month Erasmus+ traineeship from June 2027."))

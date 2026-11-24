# StudyGraph AI - Backend Starter (Kişi 1)

Bu paket **yalnızca ilk FastAPI iskeletini** oluşturur. Grafik motoru, puanlama, öneri sistemi, veritabanı ve entegrasyonlar henüz yazılmamıştır.

## Proje klasörüne ekleme

Bu paketteki `backend/` klasörünü StudyGraph-AI repository kök dizinine yerleştirin.

## Kurulum (Windows, PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Tarayıcıda `http://127.0.0.1:8000/docs` API dokümantasyonunu ve `http://127.0.0.1:8000/api/v1/health` sağlık uç noktasını açın.

## Testler

Ayrı bir terminalde sanal ortam etkin durumdayken `backend/` dizininden:

```powershell
python -m pytest -q
```

## Ayrılmış modüller

- `app/api/`: HTTP endpoint'leri
- `app/domain/`: İlişkiler, ön koşul grafiği, döngü tespiti gibi veritabanından bağımsız çekirdek algoritmalar
- `app/services/`: Puanlama, çalışma sırası ve tekrar sınavı sonrası güncelleme uygulama servisleri
- `tests/`: Otomatik testler

Mimari doküman ve ekibin API sözleşmesi incelenerek isimler ve veri modelleri üç üye arasında netleştirilmelidir. Bu paket ortak repo üzerinde henüz PR/commit oluşturmaz.

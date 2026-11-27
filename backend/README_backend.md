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

---

## RAG Asistanı Kurulumu, Migration ve Testler (Issue #8)

### 1. Ortam ve Bağımlılıklar (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

`backend/.env` dosyasına yalnızca yerel geliştirme veritabanı (`DATABASE_URL`) ve en az 32 baytlık `JWT_SECRET_KEY` değerlerini yazın. `.env`, `models/` ve `uploads/` Git tarafından yok sayılır.

### 2. Geliştirme Veritabanı Migration Sırası

```bash
cd backend
alembic upgrade head
```

Sıralı migration zinciri:
1. `0001_create_users`
2. `0002_create_courses_enrollments`
3. `0003_create_rag_tables`
4. `0004_add_chunk_embeddings`
5. `0005_create_assessment_tables` *(Issue #7 — Soru Bankası, Sınavlar ve Başarı Kayıtları; bkz. [ASSESSMENT_ARCHITECTURE.md](../docs/ASSESSMENT_ARCHITECTURE.md) ve [ASSESSMENT_API_CONTRACT.md](../docs/ASSESSMENT_API_CONTRACT.md))*

### 3. Yerel Embedding Modeli (`intfloat/multilingual-e5-small`, MIT)

Sabit revizyon `614241f622f53c4eeff9890bdc4f31cfecc418b3` üzerinden yalnızca iki dosya indirilir:

```bash
mkdir -p models/multilingual-e5-small
curl -fsSL -o models/multilingual-e5-small/model.onnx \
  "https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/onnx/model.onnx"
curl -fsSL -o models/multilingual-e5-small/tokenizer.json \
  "https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/onnx/tokenizer.json"
shasum -a 256 models/multilingual-e5-small/model.onnx models/multilingual-e5-small/tokenizer.json
```

Beklenen SHA-256 değerleri:
- `model.onnx`: `ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665`
- `tokenizer.json`: `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`

### 4. Yerel Ollama ve `qwen3:4b` (Apache-2.0)

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama serve
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3:4b
```

### 5. Backend Çalıştırma

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API dokümantasyonu: `http://127.0.0.1:8000/docs`

### 6. Testlerin Çalıştırılması (Geliştirme DB'sinden İzole)

- **Stateless birim ve API testleri** (PostgreSQL, ONNX modeli veya Ollama gerektirmez):
  ```bash
  cd backend && ../.venv/bin/python -m pytest -q
  ```
- **İzole PostgreSQL 18.1 regresyon testleri** (geliştirme DB'sine dokunmaz; geçici `--tmpfs` konteyner, port `127.0.0.1:5433`, veritabanı `studygraph_test`):
  ```bash
  docker run --rm -d --pull=never --name studygraph-pg-test \
    -p 127.0.0.1:5433:5432 --tmpfs /var/lib/postgresql \
    -e POSTGRES_USER=studygraph_test -e POSTGRES_PASSWORD="<TEST_PASS>" \
    -e POSTGRES_DB=studygraph_test postgres:latest

  cd backend
  TEST_DATABASE_URL="postgresql+psycopg://studygraph_test:<TEST_PASS>@127.0.0.1:5433/studygraph_test" \
  STUDYGRAPH_ALLOW_DESTRUCTIVE_DB_TESTS=1 \
  ../.venv/bin/python -m pytest -q

  docker stop studygraph-pg-test
  ```
- **Ayrı gerçek model testleri** (indirilmiş E5 ONNX ve yerel Ollama gerektirir):
  ```bash
  cd backend
  STUDYGRAPH_RUN_REAL_MODEL_TESTS=1 ../.venv/bin/python -m pytest tests/rag/test_onnx_e5_real_model.py -v
  STUDYGRAPH_RUN_REAL_LLM_TESTS=1 ../.venv/bin/python -m pytest tests/rag/test_real_rag_e2e.py -v -s
  ```

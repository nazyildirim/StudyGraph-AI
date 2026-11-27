# StudyGraph AI — RAG API Entegrasyon Sözleşmesi (Issue #8)

> **Durum:** Backend uçları uygulandı ve otomatik birim/PostgreSQL API testleriyle doğrulandı. Gerçek tarayıcı üzerinden React frontend entegrasyonu henüz gerçekleştirilmemiştir (frontend `USE_MOCK = true` durumundadır).

---

## 1. Genel Kurallar

- **Kanonik Taban Yol:** `/api/v1`
- **Öneksiz Frontend Uyumluluk Uçları:** Mevcut `FRONTEND/src/api/api.js` ile uyum için öneksiz yollar da sunulur (`include_in_schema=False`). Her iki grup **aynı** `MaterialService`, `RagAssistantService`, JWT authentication ve `CourseAccessPolicy` mekanizmalarını kullanır.
- **Kimlik Doğrulama:** Tüm RAG uçları `Authorization: Bearer <access_token>` gerektirir (`POST /api/v1/auth/login` üzerinden alınır).
- **CORS:** Varsayılan izinli origin'ler `http://localhost:5173` ve `http://127.0.0.1:5173` (`CORS_ALLOWED_ORIGINS` ile yapılandırılır, wildcard `*` yasaktır, `allow_credentials=false`). İzinli başlıklar: `Authorization`, `Content-Type`.
- **Dosya Yükleme Sınırları:** Varsayılan maksimum `10 MB` (`UPLOAD_MAX_BYTES`), yalnızca `.pdf` (`application/pdf`, `%PDF-` imzası) ve `.txt` (`text/plain`, UTF-8), PDF başına en fazla `200` sayfa ve `500.000` karakter.

---

## 2. Rol ve Yetki Matrisi

| İşlem | `student` (aktif kayıtlı) | `student` (kayıtsız / dropped) | `instructor` (ders sahibi) | `instructor` (başka ders) | `admin` | Anonim / Geçersiz JWT |
| --- | --- | --- | --- | --- | --- | --- |
| Materyal listele / detay gör | ✅ `200` | ❌ `404` | ✅ `200` | ❌ `404` | ✅ `200` | ❌ `401` |
| Materyal ekle (JSON / Upload) | ❌ `403` | ❌ `403` | ✅ `201` | ❌ `404` | ✅ `201` | ❌ `401` |
| Materyal sil | ❌ `403` | ❌ `403` | ✅ `204` / `200` | ❌ `404` | ✅ `204` / `200` | ❌ `401` |
| Asistana soru sor | ✅ `200` | ❌ `404` | ✅ `200` | ❌ `404` | ✅ `200` | ❌ `401` |

*(Pasif kullanıcılar tüm uçlarda reddedilir; başka derse ait `material_id` kullanımı `404` döner.)*

---

## 3. Canonical `/api/v1` Endpoint'leri

### 3.1 Materyal Listeleme
- `GET /api/v1/courses/{course_id}/materials` → `200 OK` (`list[MaterialResponse]`)

### 3.2 Materyal Detayı
- `GET /api/v1/courses/{course_id}/materials/{material_id}` → `200 OK` (`MaterialResponse`)

### 3.3 JSON Metin Materyali Oluşturma
- `POST /api/v1/courses/{course_id}/materials` (`Content-Type: application/json`)
- **Request:**
```json
{
  "title": "Hafta 2 - C İşaretçiler",
  "text": "C dilinde işaretçi başka bir değişkenin bellek adresini saklar.",
  "page": 1,
  "outcome_id": "k1"
}
```
*(Not: `outcomeId` alias'ı da kabul edilir; `learning_outcomes` henüz olmadığı için doğrulanmamış referans olarak saklanır ve yetkilendirmede kullanılmaz.)*
- **Response (`201 Created`):** Tek `MaterialResponse` nesnesi (`file_path` asla dönmez):
```json
{
  "id": 1,
  "course_id": 1,
  "title": "Hafta 2 - C İşaretçiler",
  "file_type": "text/plain",
  "file_size": 69,
  "processing_status": "processed",
  "page_count": 1,
  "page": 1,
  "outcomeId": "k1",
  "error_message": null,
  "created_at": "2026-11-27T00:00:00Z"
}
```

### 3.4 Multipart PDF / TXT Dosya Yükleme
- `POST /api/v1/courses/{course_id}/materials/upload` (`Content-Type: multipart/form-data`)
- **Form Alanları:** `file` (zorunlu `.pdf` veya `.txt`), `title` (opsiyonel, ≤255), `outcome_id` (opsiyonel, ≤100).
- **Response (`201 Created`):** `MaterialResponse` (`processing_status`: `"processed"` veya işleme başarısızsa `"failed"` + güvenli `error_message`).
  > **Önemli (MEDIUM-1):** `201 Created`, `course_materials` kaydının oluşturulduğunu belirtir; ingestion başarısını garanti etmez. İstemci mutlaka `processing_status` alanını kontrol etmelidir. `failed` durumundaki bir kayıt silinmeden aynı `content_hash` tekrar yüklenirse `409 Conflict` döner.
  > **Sayfa Kaynağı (LOW-3):** PDF yüklemelerinde `page_start`/`page_end` gerçek PDF sayfalarından (`pdfplumber`) elde edilir; JSON metin materyallerinde ise istemcinin bildirdiği `page` (varsayılan `1`) **kullanıcı tarafından bildirilen sayfa** olarak saklanır (`extraction_report.page_source = "user_reported"`).

### 3.5 Materyal Silme
- `DELETE /api/v1/courses/{course_id}/materials/{material_id}` → `204 No Content` (gövde boş).

### 3.6 RAG Asistanına Soru Sorma
- `POST /api/v1/courses/{course_id}/assistant` (`Content-Type: application/json`)
- **Request:**
```json
{
  "question": "C dilinde işaretçi nedir?",
  "mode": "topic_explanation",
  "outcome_id": "k1"
}
```
  - `mode` değerleri: `"topic_explanation"` (varsayılan — yalnızca `{question, outcome_id}` gönderilirse bu seçilir), `"code_example"`, `"exercise"`.
- **Response (`200 OK`):**
```json
{
  "query_id": 1,
  "answer": "C dilinde işaretçi (pointer), başka bir değişkenin bellek adresini saklar [S1].",
  "sources": [
    {
      "source_id": "S1",
      "title": "C Pointers Ders Notu",
      "page": 1,
      "page_start": 1,
      "page_end": 1,
      "material_id": 1,
      "chunk_id": 1,
      "relevance_score": 0.8999
    }
  ],
  "grounded": true,
  "model_name": "qwen3:4b",
  "answer_mode": "topic_explanation",
  "retrieval_method": "semantic_e5",
  "fallback_used": false,
  "fallback_reason": null
}
```
  - Kaynak bulunamadığında: `grounded: false`, `sources: []`, `model_name: null` (uydurma kaynak üretilmez).
  - Yedek çıkarımsal modda: `fallback_used: true`, `model_name: "extractive-fallback"`, `fallback_reason: "llm_unavailable:..."` ve `answer` içinde `[Yedek Çıkarımsal Mod]` uyarısı bulunur.

---

## 4. Canonical vs. Öneksiz Frontend Uyumluluk Farkları

| Uç | Canonical (`/api/v1/...`) | Öneksiz Uyumluluk (`/courses/...`) |
| --- | --- | --- |
| `GET .../materials` | `200` `list[MaterialResponse]` | `200` `list[MaterialResponse]` |
| `POST .../materials` | `201` **tek `MaterialResponse`** (REST) | `201` **güncel `list[MaterialResponse]`** (`MaterialManager.jsx` uyumu) |
| `DELETE .../materials/{id}` | `204 No Content` (REST) | `200` **güncel `list[MaterialResponse]`** (`MaterialManager.jsx` uyumu) |
| `POST .../assistant` | `200` `AssistantResponse` | `200` `AssistantResponse` |

---

## 5. HTTP Hata Kodları

| Kod | Anlam |
| --- | --- |
| `401` | Eksik, geçersiz veya süresi dolmuş JWT |
| `403` | Rol nedeniyle yasak işlem (örn. öğrencinin materyal yüklemesi/silmesi) |
| `404` | Olmayan veya erişim yetkisi bulunmayan ders/materyal (anti-enumeration) |
| `409` | Aynı derse aynı içerik (duplicate `content_hash`) veya eşzamanlı işlem çakışması |
| `413` | Dosya boyutu sınırı aşıldı (`> UPLOAD_MAX_BYTES`) |
| `415` | Desteklenmeyen dosya uzantısı, MIME türü veya geçersiz `%PDF-` imzası |
| `422` | Geçersiz istek gövdesi, boş soru/metin, geçersiz mod veya path traversal dosya adı |
| `503` | Model kapasitesi dolu (`BoundedSemaphore`) veya embedding/LLM servisi erişilemez |

---

## 6. Frontend Ekibinin Yapması Gerekenler

*(Frontend kaynak kodları bu görev kapsamında değiştirilmemiştir.)*

1. **JWT Gönderimi:** `USE_MOCK = false` yapıldığında `POST /api/v1/auth/login` ile alınan token'ın `Authorization: Bearer <token>` başlığında gönderilmesi.
2. **Base URL ve Vite Proxy:** `FRONTEND/src/api/api.js` içindeki `BASE_URL` uzun vadede `/api/v1` kanonik uçlarına yönlendirilmelidir (geçiş sürecinde öneksiz uyumluluk uçları hazırdır).
3. **Multipart PDF Yükleme:** `POST /api/v1/courses/{courseId}/materials/upload` çağrısında `FormData` kullanılmalı ve sabit `Content-Type: application/json` başlığı **kaldırılmalıdır** (tarayıcı `boundary` ekler).
4. **Durum ve Yedek Gösterimi:** Materyal listesinde `processing_status` (`processed`/`failed`) gösterilmeli; asistan ekranında `grounded === false` ve `fallback_used === true` durumları kullanıcıya açıkça belirtilmeli; `sources[].title` ve `sources[].page` gösterilmelidir.
5. **Loading ve Timeout:** Yerel `qwen3:4b` soğuk başlangıçta `~27 s`, sıcak isteklerde `~6–15 s` sürebileceğinden sohbet ekranında yükleniyor göstergesi ve en az `60–90 s` istemci timeout değeri kullanılmalıdır.
6. **Canlı Tarayıcı Doğrulaması:** Öneksiz uçlar ve CORS preflight (`http://localhost:5173`) backend testleriyle doğrulanmıştır; ancak gerçek React tarayıcı akışı (login → materyal yükleme → sohbet) henüz canlı ortamda test edilmemiştir.

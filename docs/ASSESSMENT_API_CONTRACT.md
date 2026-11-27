# StudyGraph AI — Soru Bankası ve Sınav Sistemi API Sözleşmesi (Issue #7)

> **Prefix:** `/api/v1` (yalnızca kanonik endpoint'ler; güvensiz legacy/compat route bulunmaz)
> **Kimlik Doğrulama:** Tüm endpoint'lerde zorunlu `Authorization: Bearer <access_token>` (Issue #6 JWT)
> **Doğrulama Politikası:** Tüm request gövdelerinde `extra="forbid"`; 422 hataları `SanitizedValidationRoute` ile temizlenir (ham girdi yansıtılmaz).

---

## 1. Genel HTTP Durum Kodu ve Hata Politikası

| HTTP Kodu | Anlamı / Eşlenen Domain Hataları |
| --- | --- |
| `200 OK` | Başarılı okuma, güncelleme, silme/arşivleme, sınav teslimi veya devam eden sınav oturumunun sürdürülmesi (`resumed: true`) |
| `201 Created` | Yeni soru oluşturma veya yeni sınav oturumu oluşturma (`resumed: false`) |
| `401 Unauthorized` | Eksik/geçersiz/süresi dolmuş JWT veya pasif kullanıcı |
| `403 Forbidden` | `RoleAuthorizationError` (ör. öğrencinin soru bankasına erişimi, akademisyenin/adminin öğrenci adına sınav başlatması/teslimi) |
| `404 Not Found` | `ResourceNotFoundError`, `QuestionNotFoundError`, `AssessmentNotFoundError`, `AttemptNotFoundError`, `CrossCourseReferenceError` *(anti-enumeration: her zaman `"Resource not found."`)* |
| `409 Conflict` | `InsufficientQuestionsError`, `DiagnosticExamAlreadyCompletedError`, `DiagnosticExamRequiredError`, `NoEligibleOutcomesForRetestError`, `OutcomeNotEligibleForRetestError`, `ActiveRetestConflictError`, `AttemptAlreadyFinalizedError`, `AttemptNotCompletedError`, `QuestionArchivedError` |
| `422 Unprocessable Content` | Pydantic şema hatası (`extra="forbid"`, boolean ID, 4'ten farklı seçenek sayısı), `InvalidResponseError`, `DuplicateResponseError`, `InvalidQuestionOptionsError`, `PaginationValidationError` |
| `500 Internal Server Error` | Beklenmeyen iç hatalar (genel `ValueError` dahil); sunucu tarafında yalnızca işlem adı ve istisna türü loglanır, istemciye hassas bilgi dönülmez |

---

## 2. Soru Bankası Endpoint'leri (5 Endpoint)

### 2.1. `GET /api/v1/courses/{course_id}/questions`
- **Yetki:** Ders sahibi `instructor` veya `admin` (`student` → `403`, başka ders → `404`).
- **Query Parametreleri:** `learning_outcome_id` (opsiyonel int ≥ 1), `difficulty` (`easy` | `medium` | `hard`), `include_archived` (`bool`, varsayılan `false`), `limit` (`1..100`, varsayılan `50`), `offset` (`>= 0`, varsayılan `0`).
- **Yanıt (`200 OK`):** `list[QuestionInstructorResponse]`

### 2.2. `POST /api/v1/courses/{course_id}/questions`
- **Yetki:** Ders sahibi `instructor` veya `admin`.
- **İstek Gövdesi (`QuestionCreateRequest`):**
```json
{
  "learning_outcome_id": 1,
  "question_text": "Bir dizide ilk elemana erişim karmaşıklığı nedir?",
  "difficulty_level": "easy",
  "points": 1.0,
  "options": [
    {"option_text": "O(1)", "is_correct": true, "order_index": 0},
    {"option_text": "O(n)", "is_correct": false, "order_index": 1},
    {"option_text": "O(log n)", "is_correct": false, "order_index": 2},
    {"option_text": "O(n^2)", "is_correct": false, "order_index": 3}
  ]
}
```
- **Yanıt (`201 Created` — `QuestionInstructorResponse`):**
```json
{
  "id": 10,
  "course_id": 1,
  "learning_outcome_id": 1,
  "question_text": "Bir dizide ilk elemana erişim karmaşıklığı nedir?",
  "question_type": "multiple_choice",
  "difficulty_level": "easy",
  "points": 1.0,
  "is_active": true,
  "archived_at": null,
  "version_number": 1,
  "root_question_id": null,
  "previous_version_id": null,
  "created_by": 2,
  "created_at": "2026-11-28T00:00:00Z",
  "updated_at": "2026-11-28T00:00:00Z",
  "options": [
    {"id": 41, "option_text": "O(1)", "is_correct": true, "order_index": 0},
    {"id": 42, "option_text": "O(n)", "is_correct": false, "order_index": 1},
    {"id": 43, "option_text": "O(log n)", "is_correct": false, "order_index": 2},
    {"id": 44, "option_text": "O(n^2)", "is_correct": false, "order_index": 3}
  ]
}
```

### 2.3. `GET /api/v1/courses/{course_id}/questions/{question_id}`
- **Yetki:** Ders sahibi `instructor` veya `admin`.
- **Yanıt (`200 OK`):** `QuestionInstructorResponse` (`404` eğer soru bu derste yoksa).

### 2.4. `PUT /api/v1/courses/{course_id}/questions/{question_id}`
- **Yetki:** Ders sahibi `instructor` veya `admin`.
- **İstek Gövdesi:** `QuestionUpdateRequest` (`QuestionCreateRequest` ile aynı şema).
- **Davranış:** Soru hiç bir sınava atanmadıysa yerinde güncellenir (`was_versioned: false`). Herhangi bir `assessment_questions` kaydında geçiyorsa eski kayıt arşivlenir ve yeni versiyon oluşturulur (`was_versioned: true`, `question.id` yeni ID, `previous_question_id` eski ID). Arşivli soruyu düzenleme → `409 Conflict`.
- **Yanıt (`200 OK` — `QuestionUpdateResponse`):**
```json
{
  "question": {
    "id": 11,
    "course_id": 1,
    "learning_outcome_id": 1,
    "question_text": "Güncellenmiş soru metni",
    "question_type": "multiple_choice",
    "difficulty_level": "medium",
    "points": 2.0,
    "is_active": true,
    "archived_at": null,
    "version_number": 2,
    "root_question_id": 10,
    "previous_version_id": 10,
    "created_by": 2,
    "created_at": "2026-11-28T00:10:00Z",
    "updated_at": "2026-11-28T00:10:00Z",
    "options": [
      {"id": 45, "option_text": "A", "is_correct": true, "order_index": 0},
      {"id": 46, "option_text": "B", "is_correct": false, "order_index": 1},
      {"id": 47, "option_text": "C", "is_correct": false, "order_index": 2},
      {"id": 48, "option_text": "D", "is_correct": false, "order_index": 3}
    ]
  },
  "was_versioned": true,
  "previous_question_id": 10
}
```

### 2.5. `DELETE /api/v1/courses/{course_id}/questions/{question_id}`
- **Yetki:** Ders sahibi `instructor` veya `admin`.
- **Yanıt (`200 OK` — `QuestionDeleteResponse`):**
```json
{"question_id": 10, "archived": true}
```
*(Soru sınava atanmışsa veya alt versiyonu varsa `archived: true` ile soft-delete yapılır; hiç kullanılmadıysa fiziksel silinir ve `archived: false` döner.)*

---

## 3. Öğrenci Sınav Endpoint'leri (6 Endpoint)

> **Doğru Cevap Koruması:** Aşağıdaki sınav başlatma ve görüntüleme yanıtlarında `is_correct`, `answer`, `correct_option_id` ve `correct_answer` alanları **hiçbir seviyede bulunmaz**.

### 3.1. `POST /api/v1/courses/{course_id}/exams/initial`
- **Yetki:** Yalnızca derse aktif kayıtlı `student` (`instructor`/`admin` → `403`, kayıtsız → `404`).
- **İstek Gövdesi (opsiyonel — `InitialExamCreateRequest`):** `{"question_count": 15}` (boş bırakılırsa `Settings.exam_initial_question_count = 15`).
- **Durum Kodları:** Yeni oturumda **`201 Created`** (`resumed: false`), devam eden başlangıç sınavı varsa aynı `attempt_id` ile **`200 OK`** (`resumed: true`). Tamamlanmış başlangıç sınavı varsa veya hiç aktif soru yoksa **`409 Conflict`**.
- **Yanıt (`StudentExamResponse`):**
```json
{
  "attempt_id": 1,
  "assessment_id": 1,
  "course_id": 1,
  "assessment_type": "diagnostic",
  "status": "in_progress",
  "requested_count": 15,
  "actual_count": 15,
  "unseen_question_count": null,
  "reused_question_count": null,
  "targeted_outcome_ids": [1, 2, 3, 4, 5],
  "covered_outcome_ids": [1, 2, 3, 4, 5],
  "uncovered_outcome_ids": [],
  "difficulty": null,
  "resumed": false,
  "started_at": "2026-11-28T00:15:00Z",
  "questions": [
    {
      "question_id": 10,
      "learning_outcome_id": 1,
      "question_text": "Bir dizide ilk elemana erişim karmaşıklığı nedir?",
      "difficulty_level": "easy",
      "order_index": 0,
      "options": [
        {"option_id": 41, "option_text": "O(1)", "order_index": 0},
        {"option_id": 42, "option_text": "O(n)", "order_index": 1},
        {"option_id": 43, "option_text": "O(log n)", "order_index": 2},
        {"option_id": 44, "option_text": "O(n^2)", "order_index": 3}
      ]
    }
  ]
}
```

### 3.2. `POST /api/v1/courses/{course_id}/exams/retest`
- **Yetki:** Yalnızca derse aktif kayıtlı `student`.
- **İstek Gövdesi (opsiyonel — `RetestExamCreateRequest`):**
```json
{
  "learning_outcome_id": 2,
  "question_count": 5,
  "difficulty": "medium"
}
```
*(Tüm alanlar opsiyoneldir: `learning_outcome_id` boşsa ders genelindeki tüm `review` kazanımlarından dengeli seçim yapılır; `question_count` varsayılan `5`.)*
- **Durum Kodları:** Yeni tekrar sınavında **`201 Created`**, aynı parametrelerle devam eden tekrar sınavı varsa **`200 OK`** (`resumed: true`). Farklı hedef/zorluk/sayı ile devam eden tekrar sınavı varsa **`409 Conflict`** (`ActiveRetestConflictError`). Başlangıç sınavı tamamlanmadıysa, uygun `review` kazanım yoksa veya seçilen zorlukta soru yoksa **`409 Conflict`**.
- **Metadata:** `unseen_question_count + reused_question_count == actual_count`.

### 3.3. `GET /api/v1/courses/{course_id}/exams/attempts/{attempt_id}`
- **Yetki:** Yalnızca oturumun sahibi `student` (başka öğrenci veya başka ders → `404`).
- **Davranış:** Salt-okunur; yeni sınav oturumu oluşturmaz; `200 OK` ile `StudentExamResponse` döner (doğru cevap gizli).

### 3.4. `POST /api/v1/courses/{course_id}/exams/attempts/{attempt_id}/submit`
- **Yetki:** Yalnızca oturumun sahibi `student`.
- **İstek Gövdesi (`ExamSubmitRequest`):**
```json
{
  "answers": [
    {"question_id": 10, "selected_option_id": 41},
    {"question_id": 12, "selected_option_id": null}
  ]
}
```
*(Gönderilmeyen sorular ve `selected_option_id: null` boş cevap kabul edilir. `is_correct`, `score`, `student_id` gibi alanlar `extra="forbid"` ile `422` döner.)*
- **Yanıt (`200 OK` — `ExamResultResponse`):** Genel sınav puanı + gerçek `LearningAnalysisService` tarafından üretilen `mastery_summary` (tek atomik transaction).
```json
{
  "attempt_id": 1,
  "assessment_id": 1,
  "course_id": 1,
  "assessment_type": "diagnostic",
  "status": "completed",
  "started_at": "2026-11-28T00:15:00Z",
  "completed_at": "2026-11-28T00:22:00Z",
  "total_questions": 2,
  "correct_count": 1,
  "incorrect_count": 0,
  "unanswered_count": 1,
  "earned_points": 1.0,
  "total_possible_points": 2.0,
  "score": 50.0,
  "results": [
    {
      "question_id": 10,
      "learning_outcome_id": 1,
      "order_index": 0,
      "selected_option_id": 41,
      "is_correct": true,
      "score_earned": 1.0,
      "points_possible": 1.0
    },
    {
      "question_id": 12,
      "learning_outcome_id": 2,
      "order_index": 1,
      "selected_option_id": null,
      "is_correct": false,
      "score_earned": 0.0,
      "points_possible": 1.0
    }
  ],
  "mastery_summary": {
    "mastery_threshold": 70.0,
    "learning_order": [1, 2, 3],
    "outcome_scores": [
      {"learning_outcome_id": 1, "correct_count": 1, "question_count": 1, "score_percent": 100.0},
      {"learning_outcome_id": 2, "correct_count": 0, "question_count": 1, "score_percent": 0.0}
    ],
    "weak_outcome_ids": [2],
    "unassessed_outcome_ids": [3],
    "blocked_outcome_ids": [3],
    "recommendations": [
      {"learning_outcome_id": 1, "status": "completed", "score_percent": 100.0, "priority_order": 1, "missing_prerequisites": [], "reason": "Basari esigine ulasildi."},
      {"learning_outcome_id": 2, "status": "review", "score_percent": 0.0, "priority_order": 2, "missing_prerequisites": [], "reason": "Basari puani esigin altinda; tekrar calisilmasi onerilir."},
      {"learning_outcome_id": 3, "status": "blocked", "score_percent": null, "priority_order": 3, "missing_prerequisites": [2], "reason": "Eksik on kosullar tamamlanmali: LO-2."}
    ]
  }
}
```
- **Çift Teslim / Abandoned:** `409 Conflict`.

### 3.5. `GET /api/v1/courses/{course_id}/exams/attempts/{attempt_id}/result`
- **Yetki:** Yalnızca oturumun sahibi `student`.
- **Davranış:** Yalnızca `status == "completed"` oturumun tarihsel sınav sonucunu döndürür (`mastery_summary: null` — geçmiş sınav sonucu ile güncel başarı haritası birbirine karıştırılmaz). Devam eden veya `abandoned` oturumda **`409 Conflict`**.

### 3.6. `GET /api/v1/courses/{course_id}/exams/history`
- **Yetki:** Derse aktif kayıtlı `student`.
- **Query:** `limit` (`1..100`, varsayılan `50`), `offset` (`>= 0`, varsayılan `0`).
- **Yanıt (`200 OK`):** `list[ExamHistoryItemResponse]` (en yeniden eskiye sıralı).

---

## 4. Salt-Okunur Kazanım, Başarı Haritası ve Öneri Endpoint'leri (3 Endpoint)

### 4.1. `GET /api/v1/courses/{course_id}/outcomes`
- **Yetki:** Derse okuma yetkisi olan `student`, `instructor` veya `admin`.
- **Yanıt (`200 OK`):**
```json
[
  {"id": 1, "course_id": 1, "code": "LO-1", "title": "Değişkenler", "description": null, "order_index": 1, "prerequisite_ids": []},
  {"id": 2, "course_id": 1, "code": "LO-2", "title": "Döngüler", "description": null, "order_index": 2, "prerequisite_ids": [1]}
]
```

### 4.2. `GET /api/v1/courses/{course_id}/mastery`
- **Yetki:** Yalnızca derse aktif kayıtlı `student` (kendi kayıtları).
- **Yanıt (`200 OK` — `CourseMasteryMapResponse`):** Değerlendirilmemiş kazanımlar `is_assessed: false`, `mastery_score: null`, `total_attempts: 0` olarak döner (asla sahte `%0` üretilmez).
```json
{
  "course_id": 1,
  "mastery_threshold": 70.0,
  "outcomes": [
    {"learning_outcome_id": 1, "code": "LO-1", "title": "Değişkenler", "is_assessed": true, "mastery_score": 100.0, "total_attempts": 1, "last_assessed_at": "2026-11-28T00:22:00Z"},
    {"learning_outcome_id": 4, "code": "LO-4", "title": "Ağaçlar", "is_assessed": false, "mastery_score": null, "total_attempts": 0, "last_assessed_at": null}
  ]
}
```

### 4.3. `GET /api/v1/courses/{course_id}/recommendations`
- **Yetki:** Yalnızca derse aktif kayıtlı `student`.
- **Yanıt (`200 OK` — `CourseRecommendationsResponse`):**
```json
{
  "course_id": 1,
  "mastery_threshold": 70.0,
  "recommendations": [
    {"learning_outcome_id": 1, "code": "LO-1", "title": "Değişkenler", "status": "completed", "priority_order": 1, "reason": "Basari esigine ulasildi.", "missing_prerequisites": [], "mastery_score": 100.0},
    {"learning_outcome_id": 2, "code": "LO-2", "title": "Döngüler", "status": "review", "priority_order": 2, "reason": "Basari puani esigin altinda; tekrar calisilmasi onerilir.", "missing_prerequisites": [], "mastery_score": 0.0},
    {"learning_outcome_id": 3, "code": "LO-3", "title": "Sıralama", "status": "blocked", "priority_order": 3, "reason": "Eksik on kosullar tamamlanmali: LO-2.", "missing_prerequisites": [2], "mastery_score": 0.0}
  ]
}
```

---

## 5. Frontend Entegrasyon Geçiş Rehberi (`origin/feature/frontend`)

Mevcut `origin/feature/frontend` dalı `USE_MOCK = true` varsayılanıyla çalışmaktadır. Gerçek backend'e geçişte aşağıdaki dosya ve fonksiyonların güncellenmesi gerekir:

| Frontend Dosyası / Fonksiyon | Mevcut Mock Davranışı | Gerekli Değişiklik |
| --- | --- | --- |
| `FRONTEND/src/api/api.js` (`USE_MOCK`, `request`) | `USE_MOCK = true`, öneksiz `BASE_URL + path` | `VITE_USE_MOCK` ortam değişkeniyle `false` yapılabilmeli; tüm yollar `/api/v1` önekiyle çağrılmalı ve `Authorization: Bearer ${sessionToken}` gönderilmeli (token bellek içi React state'te tutulmalı, `localStorage`'a yazılmamalı). |
| `api.js` (`login`) | `POST /auth/login` | `POST /api/v1/auth/login` (`{ email, password }` → `access_token`), ardından `GET /api/v1/users/me` ile profil/rol okunmalı. |
| `api.js` (`getQuestions`, `addQuestion`, `deleteQuestion`) & `QuestionManager.jsx` | `{ outcome_id, kind, difficulty, text, options: string[], answer: 0..3 }`; düzenleme yok | `GET/POST/PUT/DELETE /api/v1/courses/{courseId}/questions`; seçenekler `{ option_text, is_correct, order_index }[]` (tam 4 seçenek, tam 1 `is_correct: true`); `kind` kaldırılmalı; `PUT` yanıtında `was_versioned` ve yeni `question.id` işlenmeli; `DELETE` yanıtındaki `archived` durumu kullanıcıya gösterilmeli. |
| `api.js` (`getInitialExam`, `submitInitialExam`) & `ExamPage.jsx` / `Quiz.jsx` | `GET /courses/{id}/exams/initial`, cevaplar `{ [qId]: optionIndex }` | `POST /api/v1/courses/{courseId}/exams/initial` ile oturum başlatılıp `attempt_id` state'te saklanmalı (`201` veya devam eden oturumda `200`). `Quiz.jsx` her şık için `option.option_id` saklamalı; teslim `POST /api/v1/courses/{courseId}/exams/attempts/{attemptId}/submit` ile `{ answers: [{ question_id, selected_option_id }] }` şeklinde yapılmalı. |
| `api.js` (`getRetest`, `submitRetest`) & `RetestPage.jsx` | `GET .../outcomes/{oid}/retest?...`, `POST .../retest/submit` | `POST /api/v1/courses/{courseId}/exams/retest` (`{ learning_outcome_id?, question_count?, difficulty? }`) çağrılıp `attempt_id`, `unseen_question_count`, `reused_question_count` gösterilmeli; teslim yine aynı `POST .../attempts/{attemptId}/submit` endpoint'ine yapılmalı. |
| `api.js` (`getLearningMap`, `getRecommendation`) & `MapPage.jsx` | Tarayıcıdan doğrudan `POST /api/v1/learning-analyses` çağırıyor | Doğrudan `GET /api/v1/courses/{courseId}/outcomes`, `GET /api/v1/courses/{courseId}/mastery`, `GET /api/v1/courses/{courseId}/recommendations` ve `GET /api/v1/courses/{courseId}/exams/history` kullanılmalı. `mastery_score: null` (`is_assessed: false`) kazanımlar "Ölçülmedi" olarak çizilmeli. |
| Hata Yönetimi (`request`) | Genel `Sunucu hatası: ${res.status}` | `401` → oturum süresi doldu / login'e yönlendir; `403` → yetki hatası; `404` → kaynak bulunamadı; `409` → devam eden tekrar sınavı conflict veya yetersiz havuz mesajı (`detail`); `422` → form doğrulama uyarısı + loading state'leri yönetilmeli. |

### Ekip Kararı Gerektiren Fark: Kolay Sınav 69 Puan Tavanı
- `FRONTEND/src/api/learningLogic.js` içinde *"kolay zorlukla girilen tekrar sınavında puan en fazla `sufficient - 1` (69) sayılır"* kuralı vardır.
- Backend'deki gerçek Issue #5 `ScoringEngine` ve `RecommendationEngine` zorluk bazlı puan tavanı **uygulamaz** (`score_percent = correct / total * 100`, eşik `70.0`).
- Bu kuralın frontend'den kaldırılması ya da Issue #5 domain katmanına ekip onayıyla taşınması **ekip kararı** gerektirir.

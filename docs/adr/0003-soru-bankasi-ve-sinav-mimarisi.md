# ADR-0003: Soru Bankası ve Sınav Sistemi Mimari Kararları (Issue #7)

- **Durum:** Kabul Edildi (Aşama 0–8 implementasyonu tamamlandı)
- **Tarih:** 28 Kasım 2026
- **İlgili Issue:** #7 — Soru Bankası, Başlangıç ve Tekrar Sınavları

---

## Bağlam

StudyGraph AI platformunda öğrenme kazanımlarına bağlı çoktan seçmeli soru bankasının yönetilmesi, başlangıç (15 soru) ve tekrar (5 soru) sınavlarının uygulanması, öğrenci cevaplarının güvenli biçimde değerlendirilmesi ve sonuçların mevcut Issue #5 (`LearningAnalysisService`) başarı motoruna aktarılması gerekmektedir.

---

## Alınan Mimari Kararlar

### 1. Kullanılmış Soruların Immutable Versioning ve Soft-Delete ile Korunması
- **Karar:** Herhangi bir `assessment_questions` kaydında yer alan bir soru `ON DELETE RESTRICT` ile korunur. Düzenleme isteğinde eski kayıt `is_active = false, archived_at = now()` yapılarak yeni bir versiyon (`version_number + 1`, `root_question_id`, `previous_version_id`) oluşturulur; silme isteğinde arşivlenir.
- **Alternatifler:** (a) Yerinde güncelleme + `ON DELETE CASCADE` (geçmiş sınav sonuçlarını ve devam eden sınavları bozar — reddedildi); (b) Kullanılmış sorunun düzenlenmesini tamamen `409` ile yasaklamak (akademisyenin yazım hatası düzeltmesini engeller — reddedildi).
- **Artı/Eksi & Teknik Borç:** Tarihsel bütünlük ve devam eden sınav güvenliği %100 korunur; soy ağacı (`COALESCE(root_question_id, id)`) sayesinde yeni versiyon otomatik olarak "görülmemiş" sayılmaz. Eksi: `questions` tablosunda zamanla arşivli versiyon satırları birikir.

### 2. Canonical-Only `/api/v1` API Sözleşmesi
- **Karar:** Issue #7 için yalnızca kanonik `/api/v1/courses/{course_id}/...` endpoint'leri (`attempt_id` ve `selected_option_id` tabanlı) sunulur; eski frontend mock sözleşmesi için `compat_router` açılmaz.
- **Alternatif:** Issue #8'deki gibi öneksiz `compat_router` eklemek (`optionIndex` ve `attempt_id`'siz submit güvenlik ve çift teslim garantilerini zayıflattığı için reddedildi).
- **Artı/Eksi:** Daha güvenli, tek doğruluk kaynaklı OpenAPI sözleşmesi; frontend geçişinde `FRONTEND/src/api/api.js` uyarlaması gerekir (bkz. `docs/ASSESSMENT_API_CONTRACT.md` §5).

### 3. Başlangıç Sınavında Dengeli Round-Robin Seçimi
- **Karar:** `select_initial_exam_questions` aktif soruları soy ağacına göre tekilleştirip müfredat sırasındaki (`order_index`) kazanımlar arasında Round-Robin dağıtır (varsayılan 15 soru); yetersiz havuzda tekrar yapmadan mevcut tüm benzersiz soruları döndürür ve `uncovered_outcome_ids` metadata'sını raporlar.
- **Alternatif:** Tamamen rastgele seçim (bazı kazanımları 0 soruyla bırakma riski yüksek — reddedildi).

### 4. Tekrar Sınavında Görülmemiş Soru Önceliği
- **Karar:** `AssessmentRepository.get_seen_question_lineage_ids` yalnızca `student_responses` değil, öğrencinin başlattığı tüm oturumlardaki `assessment_questions` kayıtlarını ve `COALESCE(root_question_id, id)` soyunu görülmüş kabul eder. Tur 1'de görülmemiş soylar, yalnızca kontenjan yetmezse Tur 2'de görülmüş soylar seçilir.
- **Artı/Eksi:** Öğrencinin sınavı yarım bırakıp yeni sınav açarak soru havuzunu taraması engellenir.

### 5. Issue #5 Başarı Motorunun Adapter Pattern ile Doğrudan Entegrasyonu
- **Karar:** `MasteryIntegrationAdapter`, DB modellerini doğrudan `LearningAnalysisService.analyze(...)` domain nesnelerine dönüştürür; mevcut Issue #4/#5 kodları değiştirilmez ve HTTP loopback yapılmaz.
- **Alternatif:** `POST /api/v1/learning-analyses` endpoint'ine dahili HTTP isteği atmak (ağ gecikmesi, kimlik doğrulama ve transaction kopması riski — reddedildi).

### 6. Sınav Teslimi ve Başarı Güncellemesinin Tek Atomik Transaction Olması
- **Karar:** Cevap doğrulama, puanlama, `student_responses`, `student_assessments(completed)`, `LearningAnalysisService.analyze`, `mastery_records` upsert ve `study_recommendations` güncellemesi tek `SqlAlchemyTransactionManager` transaction'ı içinde çalışır.
- **Artı/Eksi:** Herhangi bir adımda hata olursa tam rollback yapılır; kısmi teslim veya tutarsız mastery kaydı oluşmaz.

### 7. PostgreSQL Advisory Lock ve 4 Katmanlı Lock Ordering
- **Karar:** Tier 1 (`pg_advisory_xact_lock(1001, course_id)`), Tier 2 (`pg_advisory_xact_lock((student_id << 32) | course_id)`), Tier 3 (`student_assessments FOR UPDATE` + `populate_existing=True`), Tier 4 (`questions ORDER BY id ASC FOR UPDATE`).
- **Artı/Eksi & Teknik Borç:** Deadlock'suz yüksek eşzamanlılık ve sıfır lost update; PostgreSQL'e özgüdür (SQLite'ta çalışmaz — ancak proje zaten PostgreSQL 15+/18.1 standardındadır).

### 8. Tek Aktif Tekrar Sınavı, Katı Metadata Şemaları ve Canlı Graf Öneri Projeksiyonu
- **Karar:** Aynı öğrenci ve ders için aynı anda en fazla bir `in_progress` `review` oturumu bulunabilir. Aynı parametrelerle gelen istek mevcut oturumu sürdürür (`200 OK`); farklı hedef/zorluk talebi `409 Conflict` (`ActiveRetestConflictError`) döner. Hem başlangıç (`_DiagnosticMetadata`) hem tekrar (`_RetestMetadata`) sınavlarının oluşturma anı metadata'sı yeni migration gerektirmeden `assessments.description` içinde katı Pydantic v2 şemalarıyla doğrulanarak saklanır; bozuk/eski description değerlerinde bilinmeyen sayılar uydurulmaz (`None` fallback). Ayrıca `GET /recommendations` ve tekrar sınavı uygunluk kontrolü ortak salt-okunur `compute_live_recommendations` üzerinden güncel ön koşul grafına göre hesaplanır.
- **Teknik Borç:** İleride `assessments` tablosuna ayrı bir `JSONB metadata` sütunu eklenerek insan okunabilir `description` alanından ayrılabilir.

# StudyGraph AI – Arayüz ve Backend Entegrasyonu

**Durum (28.11.2026):** Arayüz, ekibin backend'indeki tüm mevcut servislere bağlandı:
giriş/rol (#22), soru bankası ve sınavlar (#24), yapay zekâ asistanı ve ders notları (#23),
öğrenme analizi (#19). Backend'de henüz olmayan servisler için ekranlar bunu açıkça belirtir.

Arayüz iki modda çalışır:

| Mod | Komut | Ne zaman |
|---|---|---|
| **Canlı** | `npm run dev:canli` | Backend çalışırken; tüm veriler veritabanından ve yapay zekâdan gelir |
| **Demo** | `npm run dev` | Backend yokken (sunum yedeği); örnek veriyle çalışır, sağ üstte "Demo" yazar |

Mod seçimi `src/api/api.js` içinde yapılır: `liveApi.js` (canlı) ya da `mockApi.js` (demo).
Ekranlar iki modda da aynı kodu kullanır.

---

## 1. Canlı modda bağlanan servisler

| Ekran | Uç nokta | Not |
|---|---|---|
| Giriş | `POST /api/v1/auth/login`, `GET /api/v1/users/me` | Rol sunucudan gelir; token sadece bellekte tutulur |
| Kayıt | `POST /api/v1/auth/register` | Yeni kullanıcılar öğrenci olarak başlar |
| Başlangıç sınavı | `POST /courses/{id}/exams/initial`, `POST .../attempts/{aid}/submit` | Yarım kalan sınav kaldığı yerden açılır; doğru cevap tarayıcıya hiç gelmez |
| Tekrar sınavı | `POST /courses/{id}/exams/retest` (`learning_outcome_id`, `question_count`, `difficulty`) | Farklı ayarlarla yarım kalan sınav varsa geçmişten bulunup açılır |
| Öğrenme haritası | `GET /courses/{id}/outcomes`, `/mastery`, `/recommendations`, `/exams/history`, `.../attempts/{aid}/result` | Ölçülmemiş kazanım "Ölçülmedi" olarak çizilir |
| Asistan | `POST /courses/{id}/assistant` (`question`, `mode`, `outcome_id`) | Konu anlatımı / Kod örneği / Alıştırma; kaynaklar `[S1]` biçiminde; kaynaksız ve yedek mod uyarıları; 90 sn zaman aşımı |
| Ders notları | `GET/POST /courses/{id}/materials`, `POST .../materials/upload`, `DELETE .../materials/{mid}` | PDF/TXT yükleme (FormData), işlenme durumu ve hata mesajı gösterilir |
| Soru bankası | `GET/POST/PUT/DELETE /courses/{id}/questions` | 4 şık, 1 doğru; düzenlenen kullanılmış soru yeni sürüm olur; silinen kullanılmış soru arşivlenir (ekranda yazar) |
| Yönetici | `GET /admin/users`, `PATCH .../role`, `PATCH .../status` | Son aktif yöneticinin yetkisi alınamaz (409 → Türkçe mesaj) |

Hata yönetimi: `401` → "Oturumun sona erdi" mesajıyla giriş ekranına dönüş; `403/404/409/413/415/422/429/503`
için Türkçe mesaj. Sınav `409` mesajları backend'deki gerçek metinlerle eşleştirildi.

## 2. Backend'de henüz olmayanlar (ekranda belirtiliyor)

| Eksik servis | Arayüzde şu an |
|---|---|
| Ders listeleme / oluşturma | Dersler `src/config.js` dosyasından okunur; "Dersler" sekmesinde not var |
| Kazanım ve ön koşul ekleme | Kazanımlar sadece okunur; "Kazanımlar" sekmesinde not var |
| Öğrenciyi derse kaydetme | Veritabanında yapılmalı (backend ekibi) |
| Sınıf ve bireysel ilerleme raporu | "Genel Bakış"ta not var |
| Başarı eşiğini değiştirme | Eşik backend ayarı (%70), sadece gösteriliyor |
| Yöneticinin kullanıcı eklemesi | Kullanıcılar kendileri kayıt olur, yönetici rol verir |
| Öğrencinin soru havuzu büyüklüğünü görmesi | Tekrar sınavı ayarında "havuzda N" yazmaz |

## 3. Çalıştırma (canlı)

**Backend** (`backend/README_backend.md`):
```
cd backend
pip install -r requirements.txt
copy .env.example .env        (DATABASE_URL ve JWT_SECRET_KEY doldurulur)
alembic upgrade head
python -m app.cli.create_admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Asistan için ayrıca Ollama ve `qwen3:4b` modeli gerekir; yoksa asistan "yedek mod" uyarısıyla
ders notlarından doğrudan cevap verir.

**Veritabanında olması gerekenler:** ders (`courses`), kazanımlar ve ön koşulları, dersi veren
akademisyen, derse kayıtlı öğrenciler. Bunların ekranı backend'de henüz olmadığı için demo öncesi
backend ekibinin eklemesi gerekir.

**Arayüz:**
```
cd FRONTEND
npm install
npm run dev:canli
```
`src/config.js` içindeki ders kimliği (`id`) veritabanındakiyle aynı olmalı.

## 4. Test

Ekibin backend'i PostgreSQL ve Ollama gerektirdiği için bu ortamda çalıştırılamadı. Bunun yerine
sözleşme belgelerine (AUTHENTICATION.md, ASSESSMENT_API_CONTRACT.md, RAG_API_CONTRACT.md) alan
alan uyan bir test sunucusu yazıldı; 409 hata metinleri backend kodundan birebir kopyalandı,
başarı haritası ve öneriler **Ranya'nın gerçek `LearningAnalysisService` koduyla** hesaplandı.

Tarayıcıda uçtan uca 30 kontrol:

| Akış | Sonuç |
|---|---|
| Canlı modda rol seçimi ve "Demo" etiketi yok; ad profil servisinden geliyor | Geçti |
| Kayıt → giriş → ders → 15 soruluk başlangıç sınavı (backend seçti) | Geçti |
| Harita: kaynak backend, öneri İç İçe Döngüler, engelli konular, geçmiş | Geçti |
| Başlangıç sınavını ikinci kez açma → "zaten tamamladın" | Geçti |
| Asistan: Kod örneği modu, `[S1] [S2]` kaynakları; kaynaksız soru uyarısı | Geçti |
| Tekrar sınavı Zor + 3 soru → 3/3 → %0 → %100, yeni öneri Zaman Karmaşıklığı | Geçti |
| Farklı ayarla yarım kalan tekrar sınavı bulunup açıldı ve teslim edildi | Geçti |
| Yönetici: kullanıcı listesi, son yönetici koruması, öğrenciyi pasif yapma | Geçti |
| Pasif yapılan öğrencinin bir sonraki isteği → "Oturumun sona erdi" | Geçti |
| Akademisyen: rapor yok notu (öğrenciye özel servislere istek atılmıyor) | Geçti |
| Kazanımlar salt okunur, soru bankasında sınav türü seçimi yok | Geçti |
| Soru ekleme; kullanılmış soruyu düzenleme → sürüm; silme → arşiv mesajı | Geçti |
| TXT yükleme → "İşlendi"; bozuk PDF → "İşlenemedi" + hata; not silme | Geçti |

Demo modu ayrıca yeniden test edildi; önceki tüm akışlar aynen çalışıyor.

**Sınır:** Gerçek backend + PostgreSQL + Ollama ile canlı tarayıcı denemesi ekipçe yapılmalı
(bkz. bölüm 3). Sözleşmede olmayan bir davranış farkı çıkarsa düzeltme `liveApi.js` içinde yapılır.

## 5. Ekip kararları

1. **Kolay sınav tavanı:** Demo modunda "sadece kolay sorularla konu yeterli sayılmaz" kuralı var.
   Canlı modda puanlama tamamen backend'de yapıldığı için bu kural **uygulanmıyor**. Kural istenirse
   backend'in puanlama motoruna eklenmeli (Ayşenaz'ın ASSESSMENT_API_CONTRACT.md notu).
2. **Ders/kazanım yönetimi ve sınıf raporu servisleri:** Arayüz ekranları hazır (demo modunda
   çalışıyor); backend'e eklenirse `liveApi.js` içindeki ilgili fonksiyonlar bağlanır.
3. **Klasör adı:** main dalında `frontend/.gitkeep` var, arayüz `FRONTEND/` klasöründe. Windows'ta
   ikisi aynı klasör sayılır ama Linux/Mac'te iki ayrı klasör olur; birleştirmeden önce tek ada
   karar verilmeli.

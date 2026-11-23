# StudyGraph AI – Frontend (3. Kişi: Arayüz ve Kullanıcı Deneyimi)

React + Vite ile yazılmış, mobil uyumlu öğrenci ve akademisyen arayüzü.
Ek kütüphane yok: sadece React. Grafik SVG ile elle çiziliyor.

## Çalıştırma

```bash
npm install     # ilk sefer (zaten yaptıysan gerek yok)
npm run dev     # sonra tarayıcıda http://localhost:5173
```

Giriş ekranında **Öğrenci**, **Akademisyen** ya da **Yönetici** seçip herhangi bir e-posta ve şifreyle girilir (demo modu).

Windows PowerShell'de `npm` komutu "running scripts is disabled" hatası verirse `npm.cmd run dev` yaz.

Testler: `npm.cmd test` (14 birim testi). Backend açıkken: `npm.cmd run test:entegrasyon`.

## Backend entegrasyonu

Harita puanları, öğrenme sırası ve öneriler **Ranya'nın öğrenme analizi servisinden** (`POST /api/v1/learning-analyses`) gelir. Backend kapalıysa uygulama yerel hesapla çalışmaya devam eder; harita ekranında kaynak yazar. Ayrıntılar ve çalıştırma: `docs/ENTEGRASYON.md`.

## Uçtan uca akış (sunumdaki demo)

Giriş → Ders seçimi → 15 soruluk başlangıç sınavı → renkli öğrenme haritası + önerilen konu →
yapay zekâ asistanıyla çalışma (kaynak gösterimli) → 5 soruluk tekrar sınavı → güncellenmiş harita.

Akademisyen girişi, sekmeler:
- **Genel Bakış:** sınıf raporu, bireysel öğrenci ilerlemesi (ilk sınav → son durum), başarı eşikleri, demo verisini sıfırlama
- **Dersler:** yeni ders ekleme/silme. Ders, en az 1 kazanım ve 1 başlangıç sorusu olunca öğrencilere açılır
- **Kazanımlar:** kazanım ekleme/silme, ön koşul bağlantıları (döngü oluşturan bağlantı engellenir)
- **Soru Bankası:** kazanıma bağlı çoktan seçmeli soru ekleme (başlangıç veya tekrar sınavı için, kolay/orta/zor)
- **Ders Notları:** asistanın kaynak olarak kullandığı notları ekleme

Yönetici girişi: kullanıcı ekleme, rol değiştirme, hesabı pasif/aktif yapma ve rol-yetki matrisi. Son aktif yöneticinin yetkisi kaldırılamaz.

**Tekrar sınavı ayarları:** öğrenci zorluğu (Karışık / Kolay / Orta / Zor) ve soru sayısını (3 / 5 / 10) kendisi seçer. Her kazanımın havuzunda 10 soru var. Sadece kolay sorularla girilen sınav konuyu "Yeterli" yapamaz (puan en fazla eşiğin 1 altına sayılır). Başlangıç sınavı herkes için sabit 15 sorudur.

Öğrenci haritasında "İlerlemem" bölümü her kazanımda ilk sınav puanını ve şu anki puanı karşılaştırır.

## Belgeler

- `docs/ARAYUZ_TASARIMI.md`: ekran akışı, wireframe'ler, bileşen tasarımı ve kararları, Use Case ve Sequence diyagramları
- `docs/ENTEGRASYON.md`: backend bağlantısı, çalıştırma, veri eşleştirme, test sonuçları, ekip kararları
- `docs/ARAYUZ_TESTLERI.md`: birim testleri, arayüz senaryo testleri, kullanılabilirlik testi planı
- `docs/ekran-goruntuleri/`: sunum için ekran görüntüleri

## Klasör yapısı

| Dosya | Ne işe yarar |
|---|---|
| `src/App.jsx` | Hangi ekranın gösterileceğine karar verir (sayfa geçişleri) |
| `src/api/api.js` | Ekranların veri istediği TEK yer. `USE_MOCK = true` ise örnek veriyle, `false` ise FastAPI backend ile çalışır |
| `src/api/mockData.js` | Örnek ders, 5 kazanım, 15 başlangıç + 50 tekrar sorusu (zorluk etiketli), ders notu parçaları, sınıf raporu |
| `src/api/learningLogic.js` | Demo için puanlama, seviye, döngü kontrolü ve öneri kuralları (gerçekte backend yapar) |
| `src/components/LearningGraph.jsx` | Renkli ön koşul grafiği |
| `src/components/Quiz.jsx` | Başlangıç ve tekrar sınavında ortak kullanılan sınav bileşeni |
| `src/components/Header.jsx` | Role göre değişen üst menü |
| `src/pages/AdminPage.jsx` | Yönetici: kullanıcı ve rol yönetimi |
| `src/api/learningLogic.test.js` | Birim testleri |
| `src/api/entegrasyon.test.js` | Backend entegrasyon testi |
| `src/components/instructor/*.jsx` | Akademisyen panelinin sekmeleri (ders, kazanım, soru, not yönetimi, genel bakış) |
| `src/pages/*.jsx` | Ekranlar: Login, Courses, Exam, Map, Study, Retest, Instructor |

## Diğer servisleri bağlama

Giriş, ders, sınav, soru bankası, not, asistan ve rapor servisleri backend'de yazıldıkça
`src/api/api.js` içindeki ilgili fonksiyonlar gerçek yollarla eşleştirilir (`USE_MOCK`).
Ekran dosyalarında değişiklik gerekmez.

## Henüz yapılmayanlar (dürüst durum)

- Backend'de şu an sadece öğrenme analizi servisi var; diğer servisler yazılınca bağlanacak (`docs/ENTEGRASYON.md`, bölüm 5).
- Yapay zekâ asistanı demo modunda ders notlarından kelime eşleşmesiyle parça getiriyor; gerçek LLM cevabı backend RAG servisi bağlanınca gelecek.
- Ders notu demo modunda metin olarak yapıştırılıyor; PDF yükleme ve otomatik parçalama backend RAG servisiyle gelecek.
- Sınıf raporu örnek veri (sadece Algoritma Analizi dersi için).
- Soru düzenleme yok (silip yeniden eklenir).
- Gerçek kullanıcılarla kullanılabilirlik testi henüz yapılmadı (plan `docs/ARAYUZ_TESTLERI.md` içinde).
- Arayüz senaryo testleri otomatik tarayıcıyla çalıştırıldı ama test kodu projeye eklenmedi; sonuçları belgede.

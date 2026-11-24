
# StudyGraph AI — Bireysel Teknik Katkı Raporu

**Öğrenci:** Ranya Sönmez  
**Proje:** StudyGraph AI  
**Ders:** Yazılım Tasarımı ve Mimarisi  
**Sorumluluk Alanı:** Backend Mimarisi ve Öğrenme Algoritmaları

## 1. Gerçekleştirilen Çalışmalar

StudyGraph AI projesinde backend altyapısının oluşturulması
ve kişiselleştirilmiş öğrenme algoritmalarının geliştirilmesi
görevlerini üstlendim.

FastAPI kullanarak REST API altyapısını oluşturdum.
Öğrenme algoritmalarını Modüler Katmanlı Mimari
yaklaşımıyla API, Service ve Domain katmanlarına ayırdım.

Geliştirdiğim temel bileşenler:

- **Graph Engine:** Öğrenme kazanımları arasındaki
  ön koşul ilişkilerini yöneten, döngüleri engelleyen
  ve topolojik sıralama oluşturan algoritma.

- **Scoring Engine:** Sınav sonuçlarından kazanım
  bazlı başarı yüzdesi hesaplayan algoritma.

- **Recommendation Engine:** Başarı puanları ve
  ön koşulları değerlendirerek kişiselleştirilmiş
  çalışma önerileri üreten algoritma.

- **LearningAnalysisService:** Üç algoritmayı ortak
  bir öğrenme analizi sürecinde birleştiren servis.

Ayrıca POST /api/v1/learning-analyses endpoint'ini
geliştirerek öğrenme analizinin API üzerinden
gerçekleştirilmesini sağladım.

## 2. Mimari Tasarım ve Teknik Kararlar

Tasarımda Separation of Concerns, Single Responsibility
Principle (SRP), Low Coupling ve Dependency Injection
ilkelerini dikkate aldım.

Öğrenme algoritmalarını FastAPI ve veritabanı
teknolojilerinden bağımsız geliştirdim.

Mimari kararları açıklamak amacıyla ADR-0001
belgesini hazırladım.

Ayrıca geliştirdiğim sınıfların sorumluluklarını
ve ilişkilerini göstermek için Backend UML
Sınıf Diyagramı belgesini oluşturdum.

## 3. Test ve Doğrulama

Graph Engine, Scoring Engine, Recommendation Engine,
LearningAnalysisService ve API katmanı için
otomatik testler geliştirdim.

Toplam 41 test başarıyla tamamlandı.

Swagger üzerinden öğrenme analizi endpoint'ini
test ederek HTTP 200 yanıtını doğruladım.

## 4. GitHub ve Ekip Çalışması

Geliştirmelerimi feature/backend-foundation
branch'inde gerçekleştirdim.

Kodları, testleri ve mimari belgeleri GitHub'a
gönderdim ve kod incelemesi için Pull Request
oluşturdum.

Backend modülünü, ekip arkadaşlarımın geliştirdiği
veritabanı, sınav ve frontend bileşenleriyle
entegre edilebilecek şekilde modüler tasarladım.

## 5. Mevcut Durum ve Sonraki Çalışmalar

Backend'in ilk işlevsel sürümü ve mimari
dokümantasyonu tamamlanmıştır.

Veritabanı, kimlik doğrulama, sınav sistemi
ve frontend ile uçtan uca entegrasyon
çalışmaları henüz tamamlanmamıştır.

Kod incelemesi ve ekip içi entegrasyon
sonraki aşamalarda gerçekleştirilecektir.

## 6. GitHub Bağlantısı

https://github.com/nazyildirim/StudyGraph-AI/tree/feature/backend-foundation

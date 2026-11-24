# ADR-0001: Öğrenme Algoritmalarının Domain Katmanında Bağımsız Tasarlanması

**Tarih:** 22.11.2026  
**Durum:** Önerildi (ekip incelemesi bekleniyor)  
**Proje:** StudyGraph AI  
**İlgili Modül:** Backend ve Öğrenme Algoritmaları

## 1. Bağlam (Context)

StudyGraph AI, öğrencilerin öğrenme seviyelerini ölçerek kişiselleştirilmiş çalışma önerileri sunmayı amaçlayan web tabanlı bir eğitim platformudur.

Sistemin temel öğrenme algoritmaları:

- **Graph Engine:** Kazanımlar ve ön koşul ilişkileri
- **Scoring Engine:** Kazanım bazlı başarı puanlama
- **Recommendation Engine:** Kişiselleştirilmiş öneriler

Bu algoritmaların FastAPI, veritabanı ve kullanıcı arayüzünden bağımsız çalışabilmesi gerekmektedir.

Projenin üç kişilik bir ekip tarafından geliştirilmesi, modül sınırlarının açık olmasını önemli hâle getirmektedir.

## 2. Karar (Decision)

StudyGraph AI projesinde seçilen **Modüler Katmanlı Mimari** doğrultusunda öğrenme algoritmaları Domain katmanında geliştirilecektir.

Sorumluluk dağılımı:

- **Domain:** İş kuralları ve öğrenme algoritmaları
- **Application/Services:** Algoritmaların koordinasyonu
- **Presentation/API:** HTTP istekleri ve yanıtları
- **Infrastructure:** Veritabanı ve harici sistem erişimleri

Domain katmanı doğrudan FastAPI veya veritabanı kütüphanelerine bağımlı olmayacaktır.

API katmanı, gelen verileri doğrulayarak Application katmanına aktaracaktır.

LearningAnalysisService, öğrenme analizi işlemlerini koordine edecektir.

## 3. Değerlendirilen Alternatifler

### Alternatif A: Tüm işlemleri API içerisinde geliştirmek

**Avantaj:**
- Başlangıçta daha az dosya ve sınıf gerektirir.

**Dezavantajlar:**
- İş mantığı HTTP katmanına bağımlı olur.
- Bağımsız test yapmak zorlaşır.
- Kodun bakım maliyeti artabilir.

### Alternatif B: Modüler Katmanlı Mimari kullanmak

**Avantajlar:**
- Sorumluluklar açık biçimde ayrılır.
- Algoritmalar bağımsız test edilebilir.
- Veritabanı değişikliklerinin etkisi azaltılır.
- Üç kişilik ekibin iş bölümü kolaylaşır.

**Dezavantajlar:**
- Katmanlar arasında veri dönüşümleri gerekir.
- Sorumluluk sınırlarının korunması gerekir.

Bu alternatif tercih edilmiştir.

### Alternatif C: Öğrenme algoritmalarını mikroservislere ayırmak

**Avantaj:**
- Algoritmalar bağımsız dağıtılabilir ve ölçeklenebilir.

**Dezavantajlar:**
- Servisler arası iletişim karmaşıklaşır.
- Ağ hataları ve dağıtım maliyetleri artar.
- Mevcut ekip ve proje takvimi için gereksiz operasyonel yük oluşturabilir.

Bu nedenle ilk sürümde tercih edilmemiştir.

## 4. Kararın Sonuçları (Consequences)

### Olumlu Sonuçlar

- Öğrenme algoritmaları birbirinden ayrılmıştır.
- Domain mantığı HTTP sunucusundan bağımsızdır.
- Birim testleri kolaylaştırılmıştır.
- Yeni öğrenme algoritmalarının eklenmesi için modüler bir temel oluşturulmuştur.

### Olumsuz Sonuçlar

- Katmanlar arasında veri modellerinin dönüştürülmesi gerekir.
- Bazı doğrulama kuralları farklı katmanlarda farklı amaçlarla uygulanabilir.
- Modül sınırlarının korunması için kod incelemesi ve test disiplini gereklidir.

## 5. Kalite Nitelikleri

Bu mimari kararla önceliklendirilen nitelikler:

- Bakım yapılabilirlik
- Test edilebilirlik
- Değiştirilebilirlik
- Modülerlik
- Güvenilirlik

Performans ve ölçeklenebilirlik hedefleri ilerleyen aşamalarda ölçümlerle doğrulanacaktır.

## 6. Mevcut Uygulama

Kararın uygulandığı başlıca dosyalar:

- `backend/app/domain/graph_engine.py`
- `backend/app/domain/scoring_engine.py`
- `backend/app/domain/recommendation_engine.py`
- `backend/app/domain/learning_outcome.py`
- `backend/app/services/learning_analysis_service.py`
- `backend/app/api/learning.py`

İlk geliştirme aşamasında **41 otomatik test başarıyla tamamlanmıştır.**

FastAPI öğrenme analizi endpoint'i Swagger üzerinden HTTP 200 yanıtıyla doğrulanmıştır.

## 7. Sınırlamalar ve Sonraki Çalışmalar

- Veritabanı entegrasyonu henüz tamamlanmamıştır.
- Kimlik doğrulama ve yetkilendirme entegrasyonu beklemektedir.
- Sınav sonuçlarının sunucu tarafında doğrulanması gereklidir.
- Frontend ile uçtan uca entegrasyon yapılmamıştır.
- Yük ve performans testleri henüz gerçekleştirilmemiştir.

Bu karar, ekip incelemesinden sonra kesinleştirilecektir.
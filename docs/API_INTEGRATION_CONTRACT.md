
# StudyGraph AI — API Entegrasyon Sözleşmesi

**Proje:** StudyGraph AI  
**Tarih:** 22.11.2026  
**Durum:** Taslak — Ekip onayı bekleniyor  
**İlgili Modüller:** Backend, Sınav Sistemi, Veritabanı, Frontend

## 1. Amaç

Bu belge, StudyGraph AI projesinin öğrenme analizi
API'si ile diğer sistem modülleri arasındaki veri
alışverişini tanımlar.

Amaç, farklı ekip üyelerinin geliştirdiği
modüllerin ortak bir veri formatıyla çalışmasını
sağlamaktır.

## 2. Modül Sorumlulukları

### Öğrenme Analizi Backend'i

Sorumlu: Ranya Sönmez

- Öğrenme kazanımlarını yönetir.
- Kazanımlar arasındaki ön koşulları kontrol eder.
- Öğrenme sırasını oluşturur.
- Doğru ve yanlış sonuçlarından başarı puanı hesaplar.
- Kişiselleştirilmiş çalışma önerileri üretir.

### Sınav Sistemi ve Veritabanı

- Sınav sorularını ve öğrenci cevaplarını yönetir.
- Cevap doğruluğunu sunucu tarafında hesaplar.
- Soru ile kazanım arasındaki ilişkiyi belirler.
- Öğrenme analizine güvenilir sonuçları aktarır.
- Öğrenci ilerlemesini veritabanında saklar.

Bu modüllerin entegrasyonu henüz tamamlanmamıştır.

### Frontend

- Öğrencinin öğrenme haritasını gösterir.
- Başarı puanlarını görselleştirir.
- Çalışma önerilerini kullanıcıya sunar.

Frontend, doğru/yanlış bilgisini güvenilir kaynak
olarak doğrudan belirlememelidir.

## 3. Mevcut API Endpoint'i

**HTTP Metodu:** POST

**Endpoint:**

`/api/v1/learning-analyses`

**İçerik Türü:** application/json

**Başarılı Yanıt:** HTTP 200

**Geçersiz Veri:** HTTP 422

Bu endpoint şu anda veritabanına kayıt yapmaz.
Verilen bilgiler üzerinden analiz oluşturur.

## 4. İstek Veri Modeli

### course_id

Tür: string  
Zorunlu: Evet

Analiz yapılacak dersin benzersiz kimliğidir.

### outcomes

Tür: array  
Zorunlu: Evet  
En az bir öğrenme kazanımı içermelidir.

Her kazanım şu alanlara sahiptir:

- id: string, zorunlu
- course_id: string, zorunlu
- title: string, zorunlu
- description: string, isteğe bağlı

### prerequisite_edges

Tür: array  
Zorunlu: Hayır  
Varsayılan: Boş liste

Her ilişki şu alanlara sahiptir:

- outcome_id: Ön koşula bağlı kazanım
- prerequisite_id: Önce öğrenilmesi gereken kazanım

Örnek:

B kazanımı A kazanımını gerektiriyorsa:

outcome_id = B  
prerequisite_id = A

### question_results

Tür: array  
Zorunlu: Evet  
En az bir soru sonucu içermelidir.

Her sonuç şu alanlara sahiptir:

- question_id: string
- outcome_id: string
- is_correct: boolean

is_correct yalnızca true veya false olabilir.

### mastery_threshold

Tür: float  
Zorunlu: Hayır  
Varsayılan: 70.0

Geçerli aralık: 0–100

Bu değer, kazanımın tamamlanmış kabul edilmesi
için gereken başarı yüzdesidir.

## 5. Örnek API İsteği

```json
{
  "course_id": "PYTHON",
  "outcomes": [
    {
      "id": "A",
      "course_id": "PYTHON",
      "title": "Python Temelleri",
      "description": "Temel kavramlar"
    },
    {
      "id": "B",
      "course_id": "PYTHON",
      "title": "Değişkenler",
      "description": "Değişken kullanımı"
    },
    {
      "id": "C",
      "course_id": "PYTHON",
      "title": "Döngüler",
      "description": "Döngü yapıları"
    }
  ],
  "prerequisite_edges": [
    {
      "outcome_id": "B",
      "prerequisite_id": "A"
    },
    {
      "outcome_id": "C",
      "prerequisite_id": "B"
    }
  ],
  "question_results": [
    {
      "question_id": "Q1",
      "outcome_id": "A",
      "is_correct": true
    },
    {
      "question_id": "Q2",
      "outcome_id": "B",
      "is_correct": false
    }
  ],
  "mastery_threshold": 70.0
}
```

## 6. Örnek API Yanıtı

```json
{
  "course_id": "PYTHON",
  "learning_order": [
    "A",
    "B",
    "C"
  ],
  "scores": [
    {
      "outcome_id": "A",
      "correct_count": 1,
      "question_count": 1,
      "score_percent": 100.0
    },
    {
      "outcome_id": "B",
      "correct_count": 0,
      "question_count": 1,
      "score_percent": 0.0
    }
  ],
  "recommendations": [
    {
      "outcome_id": "A",
      "status": "completed",
      "score_percent": 100.0,
      "missing_prerequisites": []
    },
    {
      "outcome_id": "B",
      "status": "review",
      "score_percent": 0.0,
      "missing_prerequisites": []
    },
    {
      "outcome_id": "C",
      "status": "blocked",
      "score_percent": null,
      "missing_prerequisites": ["B"]
    }
  ]
}
```

## 7. Öneri Durumları

### completed

Kazanım, belirlenen başarı eşiğine ulaşmıştır.

### review

Kazanım değerlendirilmiştir ancak başarı
puanı eşik değerin altındadır ve doğrudan
ön koşulları tamamlanmıştır.

### study

Kazanım henüz değerlendirilmemiştir ve
doğrudan ön koşulları tamamlanmıştır.

### blocked

Kazanımın tamamlanmamış doğrudan
ön koşulları bulunmaktadır.

## 8. Doğrulama ve Hata Yönetimi

Mevcut backend aşağıdaki durumlarda isteği reddeder:

- Boş veya geçersiz ders kimliği
- Boş kazanım listesi
- Boş soru sonucu listesi
- Hatalı başarı eşiği
- Tanımlanmamış kazanım ilişkileri
- Döngü oluşturan ön koşullar
- Tekrarlanan soru kimlikleri
- Tanımlanmamış kazanıma ait soru sonucu
- Beklenmeyen veri alanları
- Boolean olmayan is_correct değeri

Geçersiz isteklerde HTTP 422 döndürülür.

## 9. Güvenlik ve Entegrasyon Kuralları

Mevcut API, is_correct değerini gönderilen
istekten almaktadır.

Bu nedenle mevcut endpoint, doğrudan
öğrencilerin göndereceği güvenilmeyen
sınav sonuçları için kullanıma hazır değildir.

Gerçek entegrasyonda:

1. Öğrenci cevaplarını sınav sistemine gönderir.
2. Sınav sistemi cevapları sunucuda doğrular.
3. Sınav sistemi doğru/yanlış sonuçlarını üretir.
4. Güvenilir sonuçlar öğrenme analizine aktarılır.
5. Başarı puanları ve öneriler hesaplanır.
6. Gerekli sonuçlar veritabanında saklanır.

Kimlik doğrulama ve yetkilendirme entegrasyonu
tamamlanmadan endpoint üretim ortamında
güvenilir bir öğrenci değerlendirme arayüzü
olarak kullanılmamalıdır.

## 10. Entegrasyon Öncesi Ekip Kararları

Aşağıdaki konular ekipçe netleştirilecektir:

- Ders ve kazanım kimliklerinin veri türleri
- Soru ve kazanım eşleştirme yöntemi
- Sınav sonucunun backend'e aktarılma yöntemi
- Öğrenci kimliğinin doğrulanması
- Öğrenme analizinin ne zaman çalıştırılacağı
- Analiz sonuçlarının veritabanına kayıt yöntemi
- Frontend'in analiz sonuçlarını alma yöntemi
- Öğrenci ilerlemesinin geçmişe dönük takibi

Mevcut API sözleşmesinde kimlikler string türündedir.

## 11. Mevcut Durum

Tamamlanan çalışmalar:

- FastAPI öğrenme analizi endpoint'i
- Graph Engine
- Scoring Engine
- Recommendation Engine
- LearningAnalysisService
- 56 başarılı otomatik test

Bekleyen çalışmalar:

- Sınav sistemi entegrasyonu
- Veritabanı bağlantısı
- Kimlik doğrulama ve yetkilendirme
- Frontend entegrasyonu
- Uçtan uca testler

Bu belge, ekip üyelerinin ortak veri formatı
üzerinde anlaşması için hazırlanmıştır.

Entegrasyon sırasında alınacak yeni kararlar
belgeye yansıtılacaktır.

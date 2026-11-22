
# StudyGraph AI — Backend UML Tasarımı

## 1. Amaç

Bu belge, StudyGraph AI projesinin Backend ve Öğrenme
Algoritmaları modülünde geliştirilen sınıfları ve
aralarındaki ilişkileri göstermektedir.

Ana sistemin UML tasarımı docs/UML_DIAGRAMS.md
dosyasında bulunmaktadır.

Bu belge, mevcut backend uygulamasının sınıf
seviyesindeki tasarımını açıklamak için hazırlanmıştır.

## 2. Backend Class Diagram

```mermaid
classDiagram
    direction TB

    class LearningOutcome {
        +str id
        +str course_id
        +str title
        +str description
    }

    class GraphEngine {
        -dict _outcomes
        -dict _prerequisites
        +add_outcome(outcome)
        +add_prerequisite(outcome_id, prerequisite_id)
        +get_prerequisites(outcome_id) list
        +get_learning_order(course_id) list
    }

    class QuestionResult {
        +str question_id
        +str outcome_id
        +bool is_correct
    }

    class OutcomeScore {
        +str outcome_id
        +int correct_count
        +int question_count
        +float score_percent
    }

    class ScoringEngine {
        +calculate_scores(results) list
    }

    class RecommendationEngine {
        -GraphEngine _graph
        -float _mastery_threshold
        +generate(course_id, scores) list
    }

    class LearningRecommendation {
        +str outcome_id
        +str status
        +float score_percent
        +tuple missing_prerequisites
    }

    class LearningAnalysisService {
        -ScoringEngine _scoring_engine
        +analyze(course_id, outcomes, prerequisite_edges, question_results, mastery_threshold)
    }

    class LearningAnalysisResult {
        +str course_id
        +tuple learning_order
        +tuple scores
        +tuple recommendations
    }

    GraphEngine o-- LearningOutcome : manages
    ScoringEngine ..> QuestionResult : accepts
    ScoringEngine ..> OutcomeScore : produces
    RecommendationEngine --> GraphEngine : uses
    RecommendationEngine ..> OutcomeScore : accepts
    RecommendationEngine ..> LearningRecommendation : produces
    LearningAnalysisService --> ScoringEngine : uses
    LearningAnalysisService ..> GraphEngine : creates
    LearningAnalysisService ..> RecommendationEngine : creates
    LearningAnalysisService ..> LearningAnalysisResult : returns
    LearningAnalysisResult --> OutcomeScore : contains
    LearningAnalysisResult --> LearningRecommendation : contains
```

## 3. Sınıfların Sorumlulukları

### LearningOutcome
Bir derse ait öğrenme kazanımını temsil eder.
Kazanım kimliğini, ders kimliğini, başlığını ve
açıklamasını tutar.

### GraphEngine
Kazanımlar arasındaki yönlü ön koşul ilişkilerini
yönetir. Döngü kontrolü ve topolojik sıralama yapar.

### QuestionResult
Bir sınav sorusunun kazanımını ve doğru veya
yanlış değerlendirme sonucunu temsil eder.

### ScoringEngine
Sınav sonuçlarını kazanım bazında deterministik
olarak puanlar.

### OutcomeScore
Bir kazanımın doğru soru sayısını, toplam soru
sayısını ve başarı yüzdesini temsil eder.

### RecommendationEngine
Başarı puanları ve ön koşul ilişkilerini kullanarak
kişiselleştirilmiş öğrenme önerileri üretir.

### LearningRecommendation
Bir kazanıma ait öneri durumunu, başarı puanını
ve eksik ön koşullarını temsil eder.

### LearningAnalysisService
GraphEngine, ScoringEngine ve RecommendationEngine
bileşenlerini koordine eder.

### LearningAnalysisResult
Öğrenme sırasını, başarı puanlarını ve
önerileri tek sonuç nesnesinde toplar.

## 4. Mimari İlkeler

### Single Responsibility Principle
Her algoritma sınıfı kendi temel sorumluluğuna
odaklanmaktadır.

### Separation of Concerns
Domain, Application ve Presentation katmanları
birbirinden ayrılmıştır.

### Low Coupling
Öğrenme algoritmaları doğrudan FastAPI veya
veritabanı teknolojilerine bağımlı değildir.

### Dependency Injection
GraphEngine nesnesi RecommendationEngine'e
dışarıdan verilmektedir.

### Testability
Algoritmalar bağımsız birim testleriyle
doğrulanabilmektedir.

## 5. Gerçekleştirme Durumu

- GraphEngine: İlk sürüm geliştirildi.
- ScoringEngine: İlk sürüm geliştirildi.
- RecommendationEngine: İlk sürüm geliştirildi.
- LearningAnalysisService: Geliştirildi.
- FastAPI öğrenme analizi endpoint'i: Geliştirildi.
- Otomatik testler: 41 test başarılı.

## 6. Henüz Tamamlanmayan Entegrasyonlar

- PostgreSQL veritabanı bağlantısı
- Kullanıcı kimlik doğrulama ve yetkilendirme
- Sınav kayıt sistemiyle entegrasyon
- Frontend entegrasyonu
- RAG/LLM entegrasyonu

Bu diyagram mevcut backend kodunu temel almaktadır.
Sistemin diğer modülleri tamamlandıkça
entegrasyon ilişkileri güncellenecektir.

# StudyGraph AI – Arayüz Tasarımı (3. Kişi)

Bu belge, görev dağılımında 3. kişinin tasarım çıktılarını içerir:
wireframe'ler, Use Case ve Sequence diyagramlarına katkı, arayüz bileşen tasarımı.

---

## 1. Ekran akışı

```mermaid
flowchart LR
  L[Giriş] -->|Öğrenci| D[Ders seçimi]
  D --> S[Başlangıç sınavı<br/>15 soru]
  S --> H[Öğrenme haritası<br/>+ önerilen konu]
  H --> C[Çalış & Asistan<br/>kaynak gösterimli]
  C --> A[Tekrar sınavı ayarları<br/>zorluk + soru sayısı]
  A --> T[Tekrar sınavı<br/>3 / 5 / 10 soru]
  T -->|sonuç| H
  L -->|Akademisyen| P[Akademisyen paneli]
  P --> P1[Genel bakış]
  P --> P2[Dersler]
  P --> P3[Kazanımlar]
  P --> P4[Soru bankası]
  P --> P5[Ders notları]
  L -->|Yönetici| Y[Kullanıcı ve rol yönetimi]
```

---

## 2. Wireframe'ler

### Giriş
```
┌────────────────────────────────┐
│          StudyGraph AI          │
│  [Öğrenci][Akademisyen][Yönetici]│
│  E-posta  [_________________]   │
│  Şifre    [_________________]   │
│          [   Giriş yap   ]      │
└────────────────────────────────┘
```

### Öğrenme haritası
```
┌───────────────────────────────────────────────────────┐
│ Logo   Dersler  Öğrenme Haritam  Çalış & Asistan  Çıkış│
├───────────────────────────────────────────────────────┤
│ ▌Sıradaki önerilen konu: İç İçe Döngüler  [Çalış →]   │
├───────────────────────────────────────────────────────┤
│  [Değişkenler]──►[Diziler]────────────┐               │
│        └────────►[İç İçe D.]──►[Zaman K.]──►[Bubble]  │
│  ■ Yeterli  ■ Geliştirilmeli  ■ Eksik  □ Önerilen     │
├───────────────────────────────────────────────────────┤
│ İlerlemem:  Konu  ███████░░░  %70 (+37)               │
├───────────────────────────────────────────────────────┤
│ Ölçüm geçmişi (tablo)                                 │
└───────────────────────────────────────────────────────┘
```

### Sınav (başlangıç ve tekrar aynı bileşen)
```
┌───────────────────────────────────┐
│ ████████░░░░░░░  Soru 7 / 15       │
│ Soru metni                         │
│ [A] seçenek                        │
│ [B] seçenek                        │
│ [C] seçenek                        │
│ [D] seçenek                        │
│ [← Önceki]            [Sonraki →]  │
│        ● ● ● ● ● ● ◉ ○ ○ ○ ○        │
└───────────────────────────────────┘
```

### Tekrar sınavı ayarları
```
┌───────────────────────────────────────────┐
│ Zorluk                                    │
│ [Karışık][ Kolay ][ Orta ][ Zor ]         │
│  havuzda 10   3       4      3            │
│ Soru sayısı                               │
│ [ 3 soru ][ 5 soru ][ 10 soru ]           │
│ ───────────────────────────────────────── │
│ 5 soru · Karışık · ~4 dk   [Sınava başla] │
└───────────────────────────────────────────┘
```

### Çalış & Asistan
```
┌───────────────────────────────────────────┐
│ Konu: [İç İçe Döngüler ▼]  [Tekrar sınavı →]│
│ ┌───────────────────────────────────────┐ │
│ │                 [Kullanıcı sorusu]    │ │
│ │ [Asistan cevabı                    ]  │ │
│ │ [Kaynaklar: Hafta 3 Notları · s. 4 ]  │ │
│ └───────────────────────────────────────┘ │
│ [Sorunu yaz…                    ][Gönder] │
└───────────────────────────────────────────┘
```

### Akademisyen paneli
```
┌──────────────────────────────────────────────┐
│ Akademisyen Paneli            Ders: [BİM201▼]│
│ Genel Bakış | Dersler | Kazanımlar | Soru B. | Notlar │
├──────────────────────┬───────────────────────┤
│ Yeni ekleme formu    │ Mevcut kayıtlar listesi│
│ [alanlar]            │ ... [Sil]             │
│ [Ekle]               │ ... [Sil]             │
└──────────────────────┴───────────────────────┘
```

---

## 3. Bileşen tasarımı

```
App  (hangi ekranın gösterileceği, oturum, seçili ders ve konu)
├── LoginPage
├── Header  (role göre menü)
├── CoursesPage
├── ExamPage ─────────► Quiz
├── MapPage ──────────► LearningGraph
├── StudyPage  (asistan sohbeti, kaynak gösterimi)
├── RetestPage ───────► Quiz
├── InstructorPage
│   ├── ClassOverview   (sınıf raporu, bireysel ilerleme, eşikler)
│   ├── CourseManager
│   ├── OutcomeManager ─► LearningGraph
│   ├── QuestionManager
│   └── MaterialManager
└── AdminPage  (kullanıcı, rol, yetki matrisi)

api/api.js         → tüm veri istekleri (sahte mod / gerçek backend)
api/learningLogic.js → demo modunda puanlama, öneri, döngü kontrolü
api/mockData.js    → örnek veri
```

**Tasarım kararları**

| Karar | Gerekçe |
|---|---|
| Ekranlar veriyi yalnızca `api.js` üzerinden ister | Backend hazır olunca sadece bu dosya değişir; ekranlar etkilenmez (bağımlılığın tek noktada toplanması). |
| `Quiz` bileşeni iki sınavda ortak | Aynı davranış iki yerde tekrar yazılmaz; düzeltme tek yerde yapılır. |
| `LearningGraph` öğrenci ve akademisyen ekranında ortak | Öğrenci puanlarla, akademisyen puansız görür; çizim kodu bir kez yazılır. |
| Grafik ek kütüphane olmadan SVG ile çizildi | Bağımlılık sayısı düşük kalır, ön koşul sütunları (derinlik) kontrol altında. |
| Zorluk ve soru sayısı sadece tekrar sınavında seçilebilir | Başlangıç sınavı herkes için aynı ölçü olmalı; aksi hâlde harita güvenilir olmaz. |
| Sadece kolay sorularla girilen tekrar sınavı konuyu "yeterli" yapamaz | Öğrencinin kolay soru seçerek haritayı yapay olarak yeşile boyamasını engeller; puan en fazla eşiğin 1 altına sayılır. |
| "Karışık" zorlukta sorular kolay–orta–zor sırasıyla dengeli seçilir | Kısa sınavda bile her zorluktan soru gelir. |
| Doğru cevaplar sınav ekranına gönderilmez | Tarayıcıdan cevabın görülmesini engeller; puanlama sunucuda yapılır. |
| Menüler role göre gösterilir | Kullanıcı yetkisi olmayan ekranı görmez. Asıl yetki kontrolü backend'de. |
| Mobil uyum CSS medya sorgularıyla | Öğrenci telefondan sınav çözebilir, sohbet edebilir. |

---

## 4. Use Case diyagramına katkı (arayüz tarafı)

```mermaid
flowchart LR
  O((Öğrenci)) --- U1[Giriş yap]
  O --- U2[Ders seç]
  O --- U3[Başlangıç sınavını çöz]
  O --- U4[Öğrenme haritasını görüntüle]
  O --- U5[Önerilen konuyu çalış]
  O --- U6[Asistana soru sor]
  O --- U7[Tekrar sınavını çöz]
  A((Akademisyen)) --- U1
  A --- U8[Ders ekle / sil]
  A --- U9[Kazanım ve ön koşul tanımla]
  A --- U10[Soru bankasını yönet]
  A --- U11[Ders notu ekle]
  A --- U12[Sınıf raporunu incele]
  A --- U13[Başarı eşiklerini ayarla]
  Y((Yönetici)) --- U1
  Y --- U14[Kullanıcı ve rol yönet]
```

---

## 5. Sequence diyagramları

### Başlangıç sınavından haritaya
```mermaid
sequenceDiagram
  actor Ö as Öğrenci
  participant UI as ExamPage / MapPage
  participant API as api.js
  participant BE as Backend (FastAPI)
  Ö->>UI: Ders seçer
  UI->>API: getInitialExam(dersId)
  API->>BE: GET /courses/{id}/exams/initial
  BE-->>API: sorular (doğru cevap olmadan)
  API-->>UI: sorular
  Ö->>UI: cevapları gönderir
  UI->>API: submitInitialExam(dersId, cevaplar)
  API->>BE: POST /courses/{id}/exams/initial/submit
  BE-->>API: kazanım puanları
  UI->>API: getLearningMap + getRecommendation
  API->>BE: GET learning-map, GET recommendation
  BE-->>UI: grafik, puanlar, önerilen konu
  UI-->>Ö: renkli harita ve öneri
```

### Asistan (RAG) ile çalışma
```mermaid
sequenceDiagram
  actor Ö as Öğrenci
  participant UI as StudyPage
  participant API as api.js
  participant BE as Backend RAG + LLM
  Ö->>UI: Soru yazar
  UI->>API: askAssistant(dersId, soru, konuId)
  API->>BE: POST /courses/{id}/assistant
  BE->>BE: Ders notlarında ilgili parçaları bul
  BE->>BE: LLM ile cevap üret
  BE-->>API: cevap + kaynaklar
  API-->>UI: cevap + kaynaklar
  UI-->>Ö: Cevap ve "Kaynaklar: Hafta 3 Notları · s. 4"
```

### Tekrar sınavı ve harita güncellemesi
```mermaid
sequenceDiagram
  actor Ö as Öğrenci
  participant UI as RetestPage
  participant API as api.js
  participant BE as Backend
  Ö->>UI: "Tekrar sınavına geç"
  UI->>API: getRetestOptions(dersId, konuId)
  API->>BE: GET .../retest/options
  BE-->>UI: her zorlukta havuzdaki soru sayısı
  Ö->>UI: zorluk + soru sayısı seçer, "Sınava başla"
  UI->>API: getRetest(dersId, konuId, {zorluk, sayı})
  API->>BE: GET .../retest?difficulty=..&count=..
  BE-->>UI: seçilen sorular (doğru cevap olmadan)
  Ö->>UI: cevaplar
  UI->>API: submitRetest(...)
  API->>BE: POST .../retest/submit
  BE-->>UI: doğru sayısı, eski → yeni puan, sınırlama bilgisi, karar
  UI-->>Ö: Sonuç ekranı → güncellenmiş harita
```

> Not: Uç nokta yolları arayüz tarafının önerisidir; backend ile birlikte kesinleştirilmelidir.

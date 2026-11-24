# StudyGraph AI

**StudyGraph AI**, öğrencilerin öğrenme kazanımlarını analiz ederek eksik oldukları konuları belirlemeyi ve kişiselleştirilmiş çalışma yolları oluşturmayı hedefleyen yapay zekâ destekli bir öğrenme platformudur.

## Projenin Amacı

Öğrencilerin yalnızca sınav puanlarına göre değil, konu ve kazanım bazında değerlendirilmesini sağlamak; eksik öğrenmeleri belirleyerek ön koşul ilişkilerine dayalı çalışma önerileri sunmak.

## Temel Özellikler

- **Kazanım Grafiği:** Ders kazanımlarının ve ön koşul ilişkilerinin yönlü grafik yapısıyla modellenmesi.
- **Seviye Belirleme:** Öğrencinin başlangıç bilgi düzeyinin ölçülmesi.
- **Başarı Analizi:** Kazanım bazlı öğrenme düzeyinin hesaplanması.
- **Kişiselleştirilmiş Öğrenme Yolu:** Öğrencinin eksik kazanımlarına göre çalışma sırası önerilmesi.
- **Yapay Zekâ Asistanı:** Öğretim elemanının yüklediği ders materyallerine dayalı, kaynak gösteren soru-cevap sistemi.
- **Öğrenci Paneli:** Öğrenme haritası, gelişim ve değerlendirme sonuçları.
- **Akademisyen Paneli:** Öğrencilerin ve sınıfın kazanım bazlı ilerlemesinin takip edilmesi.

## Kullanılması Planlanan Teknolojiler

| Katman            | Teknoloji                    |
| ----------------- | ---------------------------- |
| Frontend          | React, JavaScript, HTML, CSS |
| Backend           | Python, FastAPI              |
| Veritabanı        | PostgreSQL                   |
| Yapay Zekâ        | LLM, RAG                     |
| Versiyon Kontrolü | Git, GitHub                  |

## Sistem Mimarisi

StudyGraph AI projesinde **Modüler Katmanlı Mimari (Modular Layered Architecture)** kullanılması planlanmaktadır. Mimari tasarımda **Clean Architecture** yaklaşımının temel prensiplerinden yararlanılmaktadır.

Sistem dört temel katman üzerinden tasarlanmaktadır:

1. **Presentation Layer (Sunum Katmanı):** React ile geliştirilecek öğrenci ve öğretim elemanı arayüzlerini içerir.
2. **Application Layer (Uygulama Katmanı):** FastAPI üzerinden API isteklerini, uygulama servislerini ve iş akışlarını yönetir.
3. **Domain Layer (Alan Katmanı):** Öğrenme grafiği, ön koşul ilişkileri, yeterlilik hesaplamaları ve kişiselleştirilmiş öneri algoritmalarını içerir.
4. **Infrastructure Layer (Altyapı Katmanı):** PostgreSQL veritabanı, veri erişim işlemleri ve RAG/LLM entegrasyonlarını kapsar.

Backend tarafında **Modular Monolith (Modüler Monolit)** yaklaşımı tercih edilmektedir. Bu sayede sistem tek bir uygulama olarak geliştirilebilirken bileşenlerin sorumlulukları birbirinden ayrılabilecektir.

### Mimari Seçimin Gerekçeleri

- **Sorumlulukların Ayrılması:** Her katmanın belirli görevleri üstlenmesi.
- **Bakım Kolaylığı:** Sistemin farklı bölümlerinin birbirinden bağımsız şekilde güncellenebilmesi.
- **Test Edilebilirlik:** Öğrenme grafiği ve öneri algoritmalarının ayrı olarak test edilebilmesi.
- **Düşük Bağımlılık:** Katmanlar arasındaki doğrudan bağımlılıkların azaltılması.
- **Ekip Çalışması:** Üç ekip üyesinin farklı modüller üzerinde çalışabilmesi.
- **Genişletilebilirlik:** Yeni algoritmaların ve yapay zekâ servislerinin sisteme eklenebilmesi.

Tasarım sürecinde **SOLID ilkeleri**, **Repository Pattern**, **Strategy Pattern** ve **Dependency Injection** yaklaşımlarından yararlanılması hedeflenmektedir.

Bu mimari henüz planlama ve geliştirme aşamasındadır; uygulama ilerledikçe teknik ayrıntılar güncellenecektir.

## Ekip ve Görev Dağılımı

| Üye    | Sorumluluk                                                                |
| ------ | ------------------------------------------------------------------------- |
| 1. Üye | Sistem mimarisi, öğrenme grafiği, başarı hesaplama ve öneri algoritmaları |
| 2. Üye | Backend, veritabanı, kimlik doğrulama, değerlendirme sistemi ve RAG       |
| 3. Üye | React arayüzü, öğrenci ve akademisyen panelleri, görselleştirme           |

## Proje Klasör Yapısı

```text
StudyGraph-AI/
├── backend/       # API, veri erişimi ve algoritmalar
├── frontend/      # React kullanıcı arayüzü
├── docs/          # UML ve proje dokümantasyonu
├── tests/         # Test dosyaları
├── README.md
└── .gitignore
```

## GitHub Proje Yönetimi

- [GitHub Repository](https://github.com/nazyildirim/StudyGraph-AI)
- [Issues — Görev Takibi](https://github.com/nazyildirim/StudyGraph-AI/issues)
- [Projects — Kanban Panosu](https://github.com/users/nazyildirim/projects/2)
- [Pull Requests](https://github.com/nazyildirim/StudyGraph-AI/pulls)

Geliştirmeler ayrı branch'lerde yürütülecek; değişiklikler Pull Request ve Code Review süreçlerinden geçirilerek ana branch'e aktarılacaktır.

## Geliştirme Durumu

**Durum: Planlama ve İlk Tasarım**

- [x] GitHub repository oluşturuldu.
- [x] Görevler GitHub Issues üzerinde tanımlandı.
- [x] GitHub Projects (Kanban) panosu hazırlandı.
- [x] Ekip için çalışma branch'leri oluşturuldu.
- [x] Sistem mimarisi dokümanı hazırlandı ve incelemeye sunuldu.
- [x] UML Component, Class ve Use Case diyagramları hazırlandı ve incelemeye sunuldu.
- [ ] Mimari ve UML dokümanlarının Pull Request incelemeleri tamamlanacak.
- [ ] Backend ve veritabanı geliştirilecek.
- [ ] Öğrenme grafiği ve öneri algoritmaları geliştirilecek.
- [ ] Frontend arayüzleri geliştirilecek.
- [ ] RAG tabanlı yapay zekâ asistanı entegre edilecek.
- [ ] Testler ve uygulama demosu hazırlanacak.

## Akademik Bilgiler

**Ders:** Yazılım Tasarımı ve Mimarisi

**Proje:** StudyGraph AI

**Ara Teslim:** 11 Kasım 2026

**Final Sunumu:** 2 Aralık 2026

---

Bu proje akademik bir yazılım geliştirme çalışması kapsamında hazırlanmaktadır.

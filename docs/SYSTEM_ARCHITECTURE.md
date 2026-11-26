# StudyGraph AI — Sistem Mimarisi

## 1. Projeye Genel Bakış

StudyGraph AI, öğrencilerin öğrenme çıktılarına yönelik yeterlilik düzeylerini analiz etmeyi ve eksik öğrenmelerine göre kişiselleştirilmiş çalışma yolları oluşturmayı hedefleyen yapay zekâ destekli bir eğitim platformudur.

Sistemde derslerin öğrenme çıktıları, aralarındaki ön koşul ilişkileriyle birlikte yönlü bir grafik yapısında modellenir. Öğrencilerin değerlendirme sonuçlarından yararlanılarak yeterlilik düzeyleri hesaplanır ve uygun öğrenme sırası önerilir.

Ayrıca öğretim elemanlarının yüklediği ders materyallerini temel alan bir RAG/LLM asistanı planlanmaktadır.

## 2. Seçilen Yazılım Mimarisi

Projede **Modüler Katmanlı Mimari (Modular Layered Architecture)** kullanılması planlanmaktadır.

Bu yaklaşım, **Clean Architecture** prensiplerinden yararlanarak sistemin farklı sorumluluklarını ayrı katmanlarda düzenlemeyi amaçlamaktadır.

Backend tarafında **Modular Monolith (Modüler Monolit)** yaklaşımı tercih edilmiştir. Böylece sistem tek bir FastAPI uygulaması olarak geliştirilebilirken işlevsel modüller birbirinden ayrılabilecektir.

Bu seçim, üç kişilik geliştirme ekibinin proje kapsamına ve akademik teslim gereksinimlerine uygun görülmektedir.

## 3. Mimari Katmanlar

### 3.1. Presentation Layer (Sunum Katmanı)

**Teknoloji:** React, JavaScript, HTML, CSS

Bu katman, öğrencilerin ve öğretim elemanlarının sistemle etkileşim kurduğu kullanıcı arayüzlerini içerir.

Planlanan sorumlulukları:

- Kullanıcı giriş ve kayıt ekranlarını sunmak.
- Öğrenme haritasını görselleştirmek.
- Değerlendirme sorularını kullanıcıya göstermek.
- Öğrencinin yeterlilik puanlarını ve ilerlemesini sunmak.
- Öğretim elemanı yönetim panelini sağlamak.
- Yapay zekâ asistanıyla etkileşim kurulmasını sağlamak.

Sunum katmanı, iş kurallarını doğrudan uygulamak yerine backend API servislerinden yararlanacaktır.

### 3.2. Application Layer (Uygulama Katmanı)

**Teknoloji:** Python, FastAPI

Bu katman, kullanıcı isteklerini karşılayarak uygulamanın iş akışlarını koordine eder.

Planlanan sorumlulukları:

- HTTP/REST API endpoint'lerini sunmak.
- Kullanıcı kimlik doğrulama ve yetkilendirme süreçlerini yönetmek.
- Değerlendirme işlemlerini koordine etmek.
- Domain servislerini çağırmak.
- Veritabanı ve yapay zekâ entegrasyonlarıyla iletişimi yönetmek.
- Sonuçları frontend tarafına iletmek.

Application Layer, öğrenme algoritmalarının ayrıntılarını doğrudan içermek yerine ilgili Domain bileşenlerini kullanacaktır.

### 3.3. Domain Layer (Alan Katmanı)

**Teknoloji:** Python

Bu katman, StudyGraph AI projesinin temel iş kurallarını ve öğrenme algoritmalarını içerir.

Planlanan sorumlulukları:

- Öğrenme çıktılarını modellemek.
- Ön koşul ilişkilerinden yönlü öğrenme grafiği oluşturmak.
- Ön koşul ilişkilerinin geçerliliğini kontrol etmek.
- Öğrencilerin yeterlilik düzeylerini hesaplamak.
- Eksik öğrenme çıktılarını belirlemek.
- Kişiselleştirilmiş çalışma sırası önermek.

**Graph Engine**, bu katmanın temel bileşenlerinden biridir.

Domain katmanının mümkün olduğunca veritabanı ve kullanıcı arayüzü teknolojilerinden bağımsız tutulması hedeflenmektedir.

### 3.4. Infrastructure Layer (Altyapı Katmanı)

**Teknolojiler:** PostgreSQL, RAG/LLM entegrasyonları

Bu katman, veri saklama ve harici servislerle iletişim gibi teknik işlemleri gerçekleştirir.

Planlanan sorumlulukları:

- Kullanıcı, ders ve değerlendirme verilerini saklamak.
- Öğrenme çıktıları ve ön koşul ilişkilerini kalıcı olarak tutmak.
- Öğrencilerin yeterlilik ve ilerleme kayıtlarını yönetmek.
- Repository implementasyonlarını sağlamak.
- Öğretim elemanlarının yüklediği ders materyallerini işlemek.
- RAG/LLM servisleriyle iletişim kurmak.

## 4. Sistemin Temel Bileşenleri

**React Frontend:** Öğrenci ve öğretim elemanı arayüzlerini sağlar.

**FastAPI Backend:** API isteklerini karşılar ve uygulama süreçlerini koordine eder.

**Graph Engine:** Öğrenme grafiği, ön koşul ilişkileri, yeterlilik hesaplama ve öneri kurallarını yönetir.

**PostgreSQL Database:** Sistemin kalıcı verilerini saklar.

**RAG / LLM Integration:** Öğretim elemanlarının sağladığı kaynaklara dayalı yapay zekâ destekli açıklamalar sunmayı hedefler.

Bu bileşenler, tek bir sistemin farklı sorumluluklarını yerine getirecek şekilde tasarlanmaktadır.

## 5. Veri Akışı (Data Flow)

Sistemin planlanan temel veri akışı şu şekildedir:

1. Öğrenci, React arayüzü üzerinden bir işlem başlatır.
2. React, ilgili isteği FastAPI endpoint'ine gönderir.
3. Application Layer, isteği doğrular ve gerekli işlemleri koordine eder.
4. İşlem türüne göre Domain Layer, PostgreSQL veya RAG/LLM entegrasyonu kullanılır.
5. Hesaplanan veya elde edilen sonuç FastAPI tarafından frontend'e iletilir.
6. React arayüzü sonucu kullanıcıya gösterir.

Örneğin öğrenci bir değerlendirmeyi tamamladığında, cevaplar backend'e gönderilir. İlgili iş kuralları kullanılarak yeterlilik puanları hesaplanır ve öğrencinin öğrenme durumu güncellenir.

## 6. SOLID İlkelerinin Kullanımı

**Single Responsibility Principle (SRP):** Her sınıfın veya modülün belirli bir sorumluluğa odaklanması hedeflenir. Örneğin yeterlilik hesaplama ve veritabanına kayıt işlemleri ayrı bileşenlerde ele alınır.

**Open/Closed Principle (OCP):** Yeni öneri algoritmalarının mevcut iş akışlarını mümkün olduğunca değiştirmeden eklenebilmesi amaçlanır.

**Liskov Substitution Principle (LSP):** Ortak arayüzleri uygulayan bileşenlerin, tanımlanan davranış sözleşmelerini koruyarak birbirlerinin yerine kullanılabilmesi hedeflenir.

**Interface Segregation Principle (ISP):** Bileşenlerin ihtiyaç duymadıkları metotlara bağımlı olmaması için küçük ve amaca yönelik arayüzler tasarlanması amaçlanır.

**Dependency Inversion Principle (DIP):** Üst düzey iş kurallarının doğrudan veritabanı veya harici servis implementasyonlarına bağımlı olmaması hedeflenir.

## 7. Planlanan Tasarım Kalıpları (Design Patterns)

### Repository Pattern

Veritabanı erişim işlemlerinin soyutlanması amacıyla kullanılacaktır.

Bu sayede Domain ve Application bileşenlerinin doğrudan PostgreSQL sorgularına bağımlı olması azaltılabilecektir.

### Strategy Pattern

Farklı öğrenme yolu önerme algoritmalarının ortak bir arayüz üzerinden kullanılabilmesi amacıyla planlanmaktadır.

Örneğin ön koşul öncelikli ve yeterlilik puanı öncelikli öneri stratejileri geliştirilebilir.

### Dependency Injection

Servislerin ihtiyaç duydukları bağımlılıkların dışarıdan sağlanması hedeflenmektedir.

Bu yaklaşım, bileşenlerin test edilmesini ve farklı implementasyonlarla değiştirilmesini kolaylaştırabilir.

## 8. Mimari Seçimin Gerekçeleri

### 8.1. Sorumlulukların Ayrılması (Separation of Concerns)

Kullanıcı arayüzü, uygulama süreçleri, öğrenme algoritmaları ve altyapı işlemleri ayrı sorumluluk alanlarında ele alınır.

Bu sayede bir bileşende yapılan değişikliğin diğer bileşenleri gereksiz yere etkilemesi azaltılabilir.

### 8.2. Bakım Kolaylığı (Maintainability)

Katmanların belirli sorumluluklara sahip olması, kodun anlaşılmasını ve güncellenmesini kolaylaştırmayı amaçlar.

### 8.3. Test Edilebilirlik (Testability)

Graph Engine gibi temel iş kurallarının, gerçek bir veritabanı veya çalışan frontend gerektirmeden birim testleriyle doğrulanabilmesi hedeflenir.

### 8.4. Düşük Bağımlılık (Low Coupling)

Arayüzler ve Dependency Injection kullanılarak bileşenler arasındaki doğrudan bağımlılıkların azaltılması planlanır.

### 8.5. Ekip Çalışması (Team Collaboration)

Üç kişilik ekipte frontend, backend ve öğrenme algoritmaları gibi farklı sorumlulukların ayrı modüllerde yürütülmesi geliştirme sürecini kolaylaştırabilir.

### 8.6. Genişletilebilirlik (Extensibility)

Yeni öneri stratejilerinin, değerlendirme yöntemlerinin veya yapay zekâ sağlayıcılarının mevcut mimariyi tamamen değiştirmeden eklenebilmesi hedeflenir.

## 9. Neden Microservices Tercih Edilmedi?

Microservices mimarisi, bağımsız servislerin geliştirilmesini ve dağıtılmasını sağlayabilir. Ancak servisler arası iletişim, ayrı dağıtım süreçleri, izleme ve hata yönetimi gibi ek karmaşıklıklar oluşturur.

StudyGraph AI, üç kişilik bir akademik proje olduğu için başlangıç aşamasında bu operasyonel karmaşıklığın gerekli olmadığı değerlendirilmiştir.

Bu nedenle **Modular Monolith** yaklaşımı tercih edilmiştir.

Bu yapı, tek bir backend uygulamasıyla geliştirme ve test süreçlerini daha basit tutarken modüler sınırların korunmasını hedeflemektedir.

## 10. Mimari Kararın Durumu

**Durum: Planlandı — uygulama ve doğrulama aşaması devam ediyor.**

Bu doküman, StudyGraph AI projesinin hedeflenen mimarisini açıklamaktadır. Burada belirtilen bileşenlerin ve tasarım kalıplarının tamamının uygulandığı iddia edilmemektedir.

Geliştirme sürecinde ortaya çıkabilecek gereksinimlere, test sonuçlarına ve teknik kısıtlara göre mimari kararlar yeniden değerlendirilebilir.

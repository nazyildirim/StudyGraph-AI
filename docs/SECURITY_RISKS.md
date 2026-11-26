# StudyGraph AI — Güvenlik Riskleri ve Sınırlamalar (Issue #6)

> **Kapsam:** Issue #6 (Kimlik Doğrulama ve Yetkilendirme) geliştirme süreci boyunca tespit edilen mevcut riskler, tasarım sınırlamaları ve üretim öncesi gereksinimler.
> **İlke:** Henüz uygulanmamış güvenlik kontrolleri uygulanmış gibi gösterilmez; her risk için mevcut durum, olası etki ve önerilen çözüm açıkça ayrılmıştır.

---

## R1. `POST /api/v1/learning-analyses` Endpoint'inin Kimlik Doğrulamasız Olması

- **Mevcut Durum:** `backend/app/api/learning.py` içindeki `POST /api/v1/learning-analyses` endpoint'i herhangi bir kimlik doğrulama (`get_current_user`) veya rol kontrolü (`require_roles`) olmadan herkese açıktır ve `is_correct` değerlerini doğrudan istemci isteğinden alır. Bu durum [API_INTEGRATION_CONTRACT.md](API_INTEGRATION_CONTRACT.md) §9'da da kabul edilmiştir. Ekip arkadaşının sorumluluğundaki bu dosyaya Issue #6 kapsamında müdahale edilmemiştir.
- **Olası Etki:** Yetkisiz kişiler sınırsız analiz isteği göndererek sunucu kaynaklarını tüketebilir (DoS: büyük `outcomes` / `prerequisite_edges` / `question_results` listeleri) ve istemci tarafından manipüle edilmiş `is_correct` verileriyle sahte yeterlilik/öneri çıktıları üretebilir.
- **Önerilen Çözüm (uygulanmadı — endpoint sahibinin onayıyla):** Endpoint'e `Depends(get_current_user)` veya uygun `require_roles(...)` koruması eklenmesi, istek listelerine makul üst sınırlar (`max_length`) konması ve Issue #7 entegrasyonunda `is_correct` değerinin yalnızca sunucu tarafındaki sınav servisinden alınması.

---

## R2. Kayıt Endpoint'inde `409 Conflict` Kaynaklı Kullanıcı Enumeration Riski

- **Mevcut Durum:** `POST /api/v1/auth/register` zaten kayıtlı bir e-posta adresi için `409 Conflict` döndürür (`app/api/auth.py`). Buna karşılık `POST /api/v1/auth/login` olmayan kullanıcı, yanlış parola ve pasif hesap için `verify_dummy()` + birebir aynı `401` ile enumeration koruması uygular.
- **Olası Etki:** Saldırgan, kayıt endpoint'ini kullanarak belirli e-posta adreslerinin sistemde kayıtlı olup olmadığını tespit edebilir.
- **Önerilen Çözüm (uygulanmadı):** Mevcut aşamada kullanıcı deneyimi için kabul edilen bir sınırlamadır. E-posta doğrulama akışı eklendiğinde kayıt endpoint'inin her zaman genel bir yanıt (`202 Accepted`) döndürüp bilgilendirmeyi e-posta üzerinden yapması ve kayıt endpoint'ine IP bazlı rate limiting eklenmesi önerilir.

---

## R3. Frontend XSS ve Access Token Saklama Riskleri

- **Mevcut Durum:** `frontend/` dizini Issue #6 kapsamında değiştirilmemiştir. Backend yalnızca JSON gövdesinde `Bearer` access token döndürür; `HttpOnly` cookie tabanlı oturum akışı henüz yoktur.
- **Olası Etki:** Bir XSS (Cross-Site Scripting) açığı oluştuğunda `localStorage` veya `sessionStorage` içinde tutulan JWT doğrudan JavaScript ile okunup dışarı sızdırılabilir. Bellek içi saklamada token kalıcı olmasa da saldırgan aktif sekme içinde kullanıcı adına yetkili istek gönderebilir.

| Saklama Yöntemi | XSS Riski | Durum / Öneri |
| --------------- | --------- | ------------- |
| `localStorage` | **Yüksek** — Herhangi bir enjekte script okuyabilir; sekme kapansa da kalıcıdır | Önerilmez |
| `sessionStorage` | **Yüksek** — Aynı okuma riski; yalnızca sekme ömrüyle sınırlıdır | Önerilmez |
| Bellek içi (React state/context) | **Orta** — Kalıcı değildir ve depolamadan okunamaz; sayfa yenilenince yeniden giriş gerekir | **Mevcut aşama için önerilen** |
| `HttpOnly` + `Secure` + `SameSite` cookie | **Düşük (okuma)** — JS token'ı okuyamaz; ancak CSRF koruması ve backend cookie desteği gerekir | Refresh token aşamasında değerlendirilecek |

- **Önerilen Çözüm (uygulanmadı — frontend ekibiyle):** Kısa token ömrü (mevcut: 30 dk), sıkı `Content-Security-Policy (CSP)`, `dangerouslySetInnerHTML` kullanımından kaçınma, RAG/LLM çıktılarının ham HTML olarak render edilmemesi ve token'ların URL veya tarayıcı loglarına asla yazılmaması.

---

## R4. Tek-Process Bellek İçi Rate Limiting Sınırlaması

- **Mevcut Durum:** `InMemoryLoginRateLimiter` (`app/core/security/rate_limit.py`) sayaçları yalnızca tek bir Python process'inin belleğinde tutar. İstemci IP'si olarak yalnızca `request.client.host` kullanılır (`X-Forwarded-For` güvenilmez kabul edilerek yoksayılır).
- **Olası Etki:** Çoklu `uvicorn`/`gunicorn` worker'ı veya birden fazla sunucu örneği çalıştırıldığında her worker kendi sayacını tutar (efektif limit worker sayısıyla çarpılır); sunucu yeniden başlatıldığında sayaçlar sıfırlanır. Reverse proxy arkasında tüm istekler aynı proxy IP'sinden geliyorsa IP limiti meşru kullanıcıları topluca etkileyebilir.
- **Önerilen Çözüm (uygulanmadı):** Mevcut `LoginRateLimiter` `Protocol` arayüzü korunarak üretim ortamı için paylaşılan Redis tabanlı atomik (Lua script) bir implementasyon eklenmesi ve güvenilen reverse proxy yapılandırmasının (`ProxyHeadersMiddleware` + güvenilir IP listesi) tanımlanması.

---

## R5. Access Token Yaşam Süresi ve Token İptal (Revocation) Sınırlamaları

- **Mevcut Durum:** Sistem yalnızca access token üretir (varsayılan 30 dk, en fazla 60 dk). Refresh token ve `jti` bazlı iptal listesi (denylist) kapsam dışıdır.
- **Olası Etki:** `get_current_user` her istekte DB'den `is_active` ve `role` kontrolü yaptığı için pasifleştirilen veya rolü düşürülen bir kullanıcının erişimi bir sonraki istekte **anında kesilir**. Ancak kullanıcının kendisi aktif kalmaya devam ederken tek bir çalınmış/sızmış token'ı "çıkış yap (logout)" ile süre dolmadan geçersiz kılmak mümkün değildir; token süresi dolana kadar (en fazla 30 dk) geçerli kalır.
- **Önerilen Çözüm (uygulanmadı):** İleriki aşamada kısa ömürlü access token (ör. 10–15 dk) + `HttpOnly` cookie ile dönen döngüsel refresh token veya Redis tabanlı `jti` denylist mekanizması eklenmesi.

---

## R6. Kaynak Sahipliği Altyapısının Issue #7 ve #8 Modüllerine Entegre Edilmemesi

- **Mevcut Durum:** `OwnershipPolicy` ve `require_resource_access` (`app/authorization/ownership.py`, `app/api/dependencies/authorization.py`) genel ve tekrar kullanılabilir altyapı olarak geliştirilmiş ve `FakeOwnerResolver` ile test edilmiştir. Ancak Issue #7 (sınav/soru bankası) ve Issue #8 (ders materyalleri/RAG) tabloları henüz geliştirilmediği için gerçek resolver entegrasyonları **yapılmamıştır**.
- **Olası Etki:** Gelecek modüller geliştirilirken ilgili endpoint'lere `require_resource_access` ve gerçek `ResourceOwnerResolver` bağlanmazsa IDOR (Insecure Direct Object Reference) zafiyeti oluşabilir.
- **Önerilen Çözüm (uygulanmadı — Issue #7 ve #8 geliştirme aşamasında):** Her ders, sınav oturumu, yeterlilik kaydı ve RAG sorgusu endpoint'inde ilgili `ResourceOwnerResolver` implementasyonunun zorunlu tutulması ve yetkisiz erişimde `404` davranışının entegrasyon testleriyle doğrulanması.

---

## R7. Geliştirme ve Test Veritabanlarının Ayrılması

- **Mevcut Durum:** Geliştirme veritabanı (`studygraph_db`, `127.0.0.1:5432`) ile yıkıcı entegrasyon test veritabanı (`studygraph_test`, `127.0.0.1:5433`, `--tmpfs /var/lib/postgresql`) birbirinden ayrılmıştır. `tests/integration/db_safety.py` dosyası G1–G8 kurallarını (açık bayrak `STUDYGRAPH_ALLOW_DESTRUCTIVE_DB_TESTS=1`, `postgresql+psycopg`, `127.0.0.1/localhost:5433`, `_test` soneki, `DATABASE_URL` ile çakışmama, canlı `current_database()` ve beklenmeyen tablo kontrolü) uygular.
- **Olası Etki:** Test güvenlik kontrolünün atlatılması veya geliştirme/üretim URL'sinin `TEST_DATABASE_URL` olarak verilmesi durumunda `alembic downgrade base` ve `TRUNCATE` işlemleri kalıcı veri kaybına yol açabilir.
- **Önerilen Çözüm (mevcut koruma + operasyonel kural):** G1–G8 kontrollerinin hiçbir koşulda devre dışı bırakılmaması, CI/CD ortamlarında testlerin yalnızca geçici container'larda çalıştırılması ve üretim veritabanı erişim bilgilerinin geliştirici makinelerinde bulunmaması.

---

## Üretim Ortamına Geçmeden Önce Gerekli İyileştirmeler (Henüz Uygulanmadı)

- [ ] **HTTPS / TLS zorunluluğu** ve HSTS başlıkları (JWT'lerin düz metin HTTP üzerinden taşınmaması).
- [x] **`backend/app/main.py` router entegrasyonu** tamamlandı (Aşama 11).
- [ ] **Sıkı CORS politikası** (`allow_origins` açık liste, `*` kullanılmaması) — frontend entegrasyonunda tanımlanacak.
- [ ] **Redis tabanlı dağıtık `LoginRateLimiter`** ve güvenilir reverse proxy IP yapılandırması.
- [ ] **`POST /api/v1/learning-analyses`** endpoint'inin ekip onayıyla kimlik doğrulama/yetkilendirme altına alınması.
- [ ] **Güvenlik denetim günlüğü (audit logging):** Başarısız girişler, rol değişiklikleri, hesap pasifleştirmeleri ve CLI admin işlemleri için (parola/token içermeyen) yapısal loglama.
- [ ] **Gizli anahtar yönetimi:** `JWT_SECRET_KEY` ve DB parolalarının secret manager üzerinden yönetilmesi ve rotasyon planı.
- [ ] **Veritabanı sürücüsü:** Üretim imajında `psycopg[binary]` yerine `psycopg[c]` veya sistem `libpq` değerlendirmesi.
- [ ] **Issue #7 ve #8 sahiplik entegrasyonu** ve kayıt endpoint'ine rate limiting + e-posta doğrulama eklenmesi.

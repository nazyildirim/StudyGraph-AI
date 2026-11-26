# StudyGraph AI — Kimlik Doğrulama ve Yetkilendirme (Issue #6)

> **Issue:** #6 — Authentication & Authorization (Tasarım kaynağı: Issue #2 — [DATABASE_DESIGN.md](DATABASE_DESIGN.md))
> **Branch:** `feature/authentication`
> **Entegrasyon Durumu:** `auth_router`, `users_router` ve `admin_users_router` `backend/app/main.py` ana uygulamasına `/api/v1` önekiyle bağlanmıştır. Kaynak sahipliği altyapısı (`OwnershipPolicy` / `require_resource_access`) ise Issue #7 ve #8 modülleri geliştirilmediği için **hazır / henüz entegre değil** durumundadır.

---

## 1. Mimari Genel Bakış

Kimlik doğrulama ve yetkilendirme modülü, projenin **Modüler Katmanlı Mimari (Modular Layered Architecture)** yapısına uygun şekilde, mevcut öğrenme motoru (`app/domain/`, `app/services/learning_analysis_service.py`, `app/api/learning.py`) ve sağlık kontrolü (`app/api/health.py`) dosyalarına dokunmadan tasarlanmıştır.

```mermaid
flowchart LR
    Client["İstemci (HTTP)"] --> Router["API Katmanı (auth.py, users.py, admin_users.py)"]
    Router --> Deps["DI Katmanı (dependencies/auth.py, authorization.py)"]
    Deps --> Services["Uygulama Servisleri (AuthService, UserProfileService, AdminUserService)"]
    Deps --> Policy["Yetkilendirme Politikaları (roles.py, ownership.py)"]
    Services --> Security["Güvenlik Bileşenleri (passwords.py, tokens.py, rate_limit.py, email.py)"]
    Services --> Repo["UserRepository (Protocol) -> SqlAlchemyUserRepository"]
    Repo --> DB["PostgreSQL 18.1 (users tablosu)"]
```

---

## 2. Katmanlar ve Dosya Sorumlulukları

| Katman | Dosya | Sorumluluk |
| ------ | ----- | ---------- |
| Yapılandırma | `backend/app/core/config.py` | Tembel yüklenen `Settings` (`pydantic-settings`), `get_settings()`, `ConfigurationError`, güvenlik alt sınırları |
| Altyapı (DB) | `backend/app/database.py` | Import anında bağlantı kurmayan tembel SQLAlchemy 2.0 `Engine`, `sessionmaker`, `get_db()` |
| ORM & Migration | `backend/app/models/base.py`, `user.py`<br>`backend/alembic/env.py`, `versions/0001_create_users.py` | `Base` (`NAMING_CONVENTION`), `User` modeli ve geri alınabilir `users` tablosu migration'ı |
| Güvenlik | `backend/app/core/security/passwords.py` | `PasswordPolicy`, `PasswordHasher` (`Protocol`), `Argon2PasswordHasher` ve tembel rastgele dummy hash |
| Güvenlik | `backend/app/core/security/tokens.py` | `TokenService` (`Protocol`), `JwtTokenService` (PyJWT HS256), `extract_bearer_token`, `validate_user_id` |
| Güvenlik | `backend/app/core/security/rate_limit.py` | `LoginRateLimiter` (`Protocol`), atomik rezervasyonlu `InMemoryLoginRateLimiter` |
| Güvenlik | `backend/app/core/security/email.py` | `normalize_email()`, `InvalidEmailError` |
| Veri Erişimi | `backend/app/repositories/user_repository.py` | `UserRepository` (`Protocol`), `SqlAlchemyUserRepository` (transaction, commit, rollback ve `FOR UPDATE` kilitleme) |
| Yetkilendirme | `backend/app/authorization/roles.py`, `ownership.py` | `Role(StrEnum)`, `check_role_access`, `ResourceOwnerResolver` (`Protocol`), `OwnershipPolicy` |
| Şemalar | `backend/app/schemas/auth.py`, `user.py` | `RegisterRequest`, `LoginRequest`, `TokenResponse`, `UserResponse`, `ProfileUpdateRequest`, `Admin*Request` |
| Servisler | `backend/app/services/auth_service.py`, `user_profile_service.py`, `admin_user_service.py` | İş akışı orkestrasyonu (SQLAlchemy oturumundan bağımsız) |
| API & DI | `backend/app/api/routing.py`, `dependencies/auth.py`, `dependencies/authorization.py`<br>`backend/app/api/auth.py`, `users.py`, `admin_users.py` | `SanitizedValidationRoute`, `get_current_user`, `require_roles`, `require_resource_access` ve HTTP router'ları |
| CLI | `backend/app/cli/create_admin.py` | `python -m app.cli.create_admin` güvenli admin oluşturma ve yükseltme aracı |

---

## 3. SOLID Prensiplerinin Uygulanışı

- **Single Responsibility (SRP):** HTTP yönlendirme (`api/`), iş kuralları (`services/`), yetkilendirme politikaları (`authorization/`), kriptografik işlemler (`core/security/`) ve kalıcılık/transaction yönetimi (`repositories/`) ayrı modüllere bölünmüştür.
- **Open/Closed (OCP):** `PasswordHasher`, `TokenService`, `LoginRateLimiter`, `UserRepository` ve `ResourceOwnerResolver` arayüzleri sayesinde mevcut servisler değiştirilmeden yeni implementasyonlar (örneğin Redis tabanlı rate limiter veya Issue #7/#8 kaynak resolver'ları) eklenebilir.
- **Liskov Substitution (LSP):** Unit/API testlerindeki `FakeUserRepository`, `FakePasswordHasher` ve `FakeOwnerResolver` sınıfları üretim sınıflarıyla aynı `Protocol` sözleşmelerini sağlar.
- **Interface Segregation (ISP):** Her güvenlik ve veri erişimi sorumluluğu küçük ve odaklı `Protocol` arayüzlerine ayrılmıştır.
- **Dependency Inversion (DIP):** `AuthService`, `UserProfileService`, `AdminUserService` ve FastAPI dependency'leri somut sınıflar yerine `Protocol` arayüzlerine bağımlıdır; somut örnekler `app/api/dependencies/auth.py` üzerinden enjekte edilir.

---

## 4. Kayıt ve Giriş Akışları

### 4.1. Kayıt Akışı (`AuthService.register`)
1. `normalize_email()` ile e-posta doğrulaması (`email-validator`, `check_deliverability=False`), baş/son boşluk temizleme, IDN normalizasyonu, tam küçük harfe çevirme ve ≤ 254 karakter kontrolü yapılır. Gmail noktaları ve `+etiket` korunur.
2. `PasswordPolicy.validate()` parolayı trim etmeden doğrular.
3. `UserRepository.get_by_email()` ile ön kontrol yapılır; asıl benzersizlik garantisi PostgreSQL `uq_users_email` kısıtıdır.
4. Parola `Argon2PasswordHasher.hash()` ile hashlenir.
5. Kullanıcı **her zaman `Role.STUDENT`** ve `is_active=True` olarak kaydedilir. `RegisterRequest` üzerinde `role` alanı yoktur (`extra="forbid"` → `422`).
6. Eş zamanlı kayıt yarışında oluşan `uq_users_email` `IntegrityError` hatası repository katmanında rollback sonrası `EmailAlreadyRegisteredError`'a çevrilir ve HTTP `409 Conflict` döner.

### 4.2. Giriş Akışı (`AuthService.login`)
1. E-posta `normalize_email()` ile normalize edilir (geçersiz format → `422`).
2. `LoginRateLimiter.acquire(client_ip, normalized_email)` ile parola doğrulamasından **önce** atomik slot rezervasyonu alınır; limit aşımında hasher çağrılmadan `429 Too Many Requests` + `Retry-After` döner.
3. Boş veya güvenli sınırların üzerindeki (`> 128` karakter veya `> 512` UTF-8 bayt) giriş parolaları doğrudan Argon2id'ye verilmez; sabit küçük bir girdiyle `verify_dummy()` çalıştırılır ve başarısızlık kaydedilir.
4. Kullanıcı yoksa veya `is_active=False` ise `verify_dummy()` çalıştırılır (zamanlama eşitlemesi).
5. Olmayan kullanıcı, yanlış parola, pasif hesap ve sınır üstü parolada birebir aynı `401 Unauthorized` (`WWW-Authenticate: Bearer`, `"Invalid email or password."`) döner.
6. Parola doğruysa ve `needs_rehash()` `True` dönerse yeni hash aynı istek içinde `update_password_hash()` ile kaydedilir.
7. Hesap rate-limit sayacı `record_success()` ile sıfırlanır ve `JwtTokenService.create_access_token()` ile yalnızca access token üretilir.

---

## 5. JWT Access Token Mekanizması

- **Kütüphane ve Algoritma:** `PyJWT` (`HS256`). Refresh token ve refresh endpoint'i ilk aşamada **kapsam dışıdır**.
- **İmza Anahtarı:** `JWT_SECRET_KEY` ortam değişkeninden okunur, en az 32 UTF-8 bayt olmalıdır; varsayılan değer yoktur.
- **Süre:** Varsayılan `30` dakika (`ACCESS_TOKEN_EXPIRE_MINUTES`, izin verilen aralık `5–60`).
- **Payload Claim'leri:** `sub` (ondalık `str` kullanıcı ID'si), `type` (`"access"`), `iss`, `aud`, `iat`, `nbf`, `exp`, `jti` (UUID4). **Token içinde `role` claim'i bulunmaz.**
- **Doğrulama Zinciri (`JwtTokenService.decode_access_token`):**
  - `extract_bearer_token()` (büyük/küçük harfe duyarsız `Bearer`, tek token).
  - Maksimum `4096` bayt uzunluk ve 3 parçalı (`xxx.yyy.zzz`) yapı kontrolü.
  - Decode öncesi header kontrolü: `alg == "HS256"` (`none`, `RS256` vb. reddedilir).
  - Zorunlu claim'ler (`sub`, `exp`, `iat`, `nbf`, `iss`, `aud`, `jti`, `type`), imza, `iss`, `aud`, `exp`, `nbf`, `iat` doğrulaması.
  - `type == "access"`, `bool` olmayan tam sayı zaman damgaları, gelecekteki `iat`/`nbf` reddi, aşırı uzun ömür (`exp - iat > expire_seconds`) reddi, kanonik UUID `jti` kontrolü.
  - `sub` kontrolü: `^[1-9][0-9]{0,9}$` ve `1 <= user_id <= 2147483647` (PostgreSQL `INTEGER` aralığı).
- **Veritabanı Doğrulaması (`get_current_user`):** Her istekte `user_repository.get_by_id(payload.user_id)` çağrılır. Kullanıcı silinmişse, `is_active=False` ise veya DB rolü geçerli `Role` enum'u dışında ise `401` döner. Token içindeki olası bir `role` claim'ine asla güvenilmez.

---

## 6. Argon2id Parola Hashleme ve Parola Politikası

- **Algoritma:** `argon2-cffi` ile `Argon2id` (`Type.ID`), varsayılan RFC 9106 profili (`time_cost=3`, `memory_cost=65536` KiB, `parallelism=4`, `hash_len=32`, `salt_len=16`). Alt sınırlar: `time_cost >= 2`, `memory_cost >= 19456`, `parallelism >= 1`.
- **Parola Politikası (`PasswordPolicy`):**
  - En az **15**, en çok **128** Unicode karakter.
  - En fazla **512** UTF-8 bayt (hash DoS koruması; bcrypt'in 72 bayt sınırı yoktur).
  - Kompozisyon zorlaması yoktur; parola trim edilmez; e-posta adresiyle aynı parola reddedilir.
- **Tembel Rastgele Dummy Hash:** Kodda sabit hash/parola yoktur. `Argon2PasswordHasher.get_dummy_hash()` ilk ihtiyaçta `secrets.token_urlsafe(32)` ile aynı Argon2id parametreleriyle bir kez üretilir ve thread-safe şekilde bellekte tutulur.
- **Hata Güvenliği:** `SanitizedValidationRoute` tüm `/auth`, `/users` ve `/admin/users` 422 hatalarından ham `input` değerlerini temizler; `SecretStr` + `hide_input_in_errors=True` ile parola hiçbir doğrulama hatasında istemciye veya loglara sızmaz.

---

## 7. Rate Limiting Mekanizması

- `InMemoryLoginRateLimiter`, tek `threading.Lock` altında **atomik rezervasyon modeli** uygular (`failures + in_flight <= limit`).
- **Limitler (varsayılan):** `(client_ip, normalized_email)` başına 15 dakikada `5` deneme; `client_ip` başına 15 dakikada `30` deneme. İki anahtar birlikte kontrol edilir; biri doluysa hiçbirine rezervasyon yapılmaz.
- **İstisna Güvenliği:** Context manager (`with limiter.acquire(...) as reservation:`) beklenmeyen istisnalarda `release()` çağırarak `in_flight` sayacının sızmasını önler.
- **LRU Bellek Sınırı:** `RATE_LIMIT_MAX_KEYS` (varsayılan `10000`) aşıldığında yalnızca `in_flight == 0` olan pasif anahtarlar çıkarılır; aktif rezervasyonu olan anahtarlar asla silinmez.
- **İstemci IP'si:** Yalnızca `request.client.host` kullanılır; güvenilmeyen `X-Forwarded-For` başlığı dikkate alınmaz.

---

## 8. Roller, Yetkilendirme ve Kaynak Sahipliği

### 8.1. Roller (`Role(StrEnum)`)
- `student`: Kendi profilini görüntüleyip güncelleyebilir; ileride kendi kayıtlarına ve değerlendirme sonuçlarına erişir.
- `instructor`: Kendi profilini yönetebilir; ileride kendi derslerine ait kaynakları yönetir.
- `admin`: `/api/v1/admin/users` yönetimi ve varsayılan kaynak sahipliği bypass (`DEFAULT_BYPASS_ROLES = {Role.ADMIN}`) yetkisine sahiptir.

### 8.2. Rol Bazlı Yetkilendirme (`require_roles`)
- **Varsayılan ret (deny by default):** İzinli rol listesi boşsa (`require_roles()`) admin dahil herkese `403 Forbidden` döner.
- Rol değeri her zaman `get_current_user` tarafından DB'den yüklenen `User.role` alanından okunur.

### 8.3. Kaynak Sahipliği Altyapısı (`OwnershipPolicy` ve `require_resource_access`)
> [!IMPORTANT]
> **Durum: Hazır / Entegre değil.** Issue #7 (sınav/soru bankası) ve Issue #8 (RAG/ders materyalleri) tabloları henüz oluşturulmadığı için gerçek `ResourceOwnerResolver` sınıfları yazılmamıştır. Altyapı yalnızca `FakeOwnerResolver` ve test-içi dummy router ile doğrulanmıştır.

- Kaynak bulunamadığında (`owner_id is None`) ve kullanıcı sahip olmadığında birebir aynı **404 Not Found** (`{"detail": "Resource not found."}`) yanıtı ve başlıkları döndürülür; kaynak varlığı ifşa edilmez.
- `{resource_id}` yolu `Path(ge=1, le=2147483647)` ile doğrulanır.

---

## 9. Profil ve Admin Yönetimi + Son Aktif Admin Koruması

- **Profil (`/api/v1/users/me`):** `GET` profili döndürür (`hashed_password` hariç). `PATCH` yalnızca `first_name` ve `last_name` alanlarını kabul eder (`ProfileUpdateRequest` `extra="forbid"` + `UserProfileService` ve `UserRepository` ikinci katman allowlist). `role`, `is_active`, `email`, `password`, `id` gönderilmesi `422` döner.
- **Admin (`/api/v1/admin/users`):** Router düzeyinde `Depends(require_roles(Role.ADMIN))` ile korunur. Kullanıcı oluşturma veya fiziksel silme yoktur; pasifleştirme `is_active=false` ile yapılır.
- **Transaction ve Son Aktif Admin Koruması:**
  - `UserProfileService` ve `AdminUserService` doğrudan SQLAlchemy oturumu kullanmaz; `commit`, `rollback` ve kilitleme sorumluluğu `SqlAlchemyUserRepository` içindedir.
  - Aktif admin sayısını azaltabilecek işlemlerde (`new_role != Role.ADMIN` veya `is_active=False`), tek transaction içinde önce `SELECT id FROM users WHERE role='admin' AND is_active IS TRUE ORDER BY id ASC FOR UPDATE` ile aktif admin satırları sabit sırada kilitlenir (deadlock önleme), hedef kullanıcı `FOR UPDATE` ile yeniden okunur ve aktif admin sayısı `0`'a düşecekse rollback yapılıp `409 Conflict` (`LAST_ACTIVE_ADMIN`) döner.

---

## 10. CLI ile Güvenli Admin Oluşturma (`app.cli.create_admin`)

Varsayılan admin veya sabit parola yoktur. Parola CLI argümanı olarak kabul edilmez.

```bash
# İnteraktif oluşturma (getpass ile iki kez sorulur)
cd backend
../.venv/bin/python -m app.cli.create_admin \
  --email admin@example.edu --first-name Ada --last-name Lovelace

# Otomasyon için stdin ile oluşturma
printf '%s\n' "$ADMIN_PASSWORD" | ../.venv/bin/python -m app.cli.create_admin \
  --email admin@example.edu --first-name Ada --last-name Lovelace --password-stdin

# Mevcut aktif kullanıcıyı açık onayla admin yapma (parola ve is_active değişmez)
../.venv/bin/python -m app.cli.create_admin \
  --email student@example.edu --promote-existing
```

- `--promote-existing` pasif kullanıcıları reddeder, `--password-stdin` ile birlikte kullanılamaz ve `--yes` verilmedikçe normalize e-postanın yeniden yazılmasını ister.
- Çıktılarda ve hata mesajlarında parola, hash ve `DATABASE_URL` asla gösterilmez.

---

## 11. Ortam Değişkenleri Kurulumu

Şablon dosya: `backend/.env.example` (tüm değerler boştur; `backend/.env` `.gitignore` kapsamındadır).

| Değişken | Zorunlu | Varsayılan / Açıklama |
| -------- | ------- | --------------------- |
| `DATABASE_URL` | DB işlemlerinde | `postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<dev_db>` |
| `JWT_SECRET_KEY` | Token işlemlerinde | En az 32 UTF-8 bayt (temsili üretim: `secrets.token_urlsafe(48)`) |
| `JWT_ISSUER` / `JWT_AUDIENCE` | Hayır | `studygraph-ai` / `studygraph-ai-api` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Hayır | `30` (izin verilen aralık: `5–60`) |
| `JWT_LEEWAY_SECONDS` | Hayır | `0` (izin verilen aralık: `0–30`) |
| `ARGON2_TIME_COST` / `MEMORY_COST` / `PARALLELISM` | Hayır | `3` / `65536` / `4` |
| `LOGIN_RATE_LIMIT_ACCOUNT_MAX` / `IP_MAX` / `WINDOW_SECONDS` / `RATE_LIMIT_MAX_KEYS` | Hayır | `5` / `30` / `900` / `10000` |

---

## 12. Aktif API Endpoint'leri

> **Not:** Tüm router'lar `backend/app/main.py` içinde `/api/v1` önekiyle aktif olarak bağlıdır ve `/docs` (Swagger) ile `/openapi.json` üzerinde görünür. Örnek değerler tamamen temsilidir.

| Metot | Yol | Yetki | Durum Kodları |
| ----- | --- | ----- | ------------- |
| `POST` | `/api/v1/auth/register` | Herkese açık | `201`, `409`, `422` |
| `POST` | `/api/v1/auth/login` | Herkese açık | `200`, `401`, `422`, `429` |
| `GET` | `/api/v1/users/me` | Giriş yapmış kullanıcı | `200`, `401` |
| `PATCH` | `/api/v1/users/me` | Giriş yapmış kullanıcı | `200`, `401`, `422` |
| `GET` | `/api/v1/admin/users` | `admin` | `200`, `401`, `403`, `422` |
| `GET` | `/api/v1/admin/users/{user_id}` | `admin` | `200`, `401`, `403`, `404`, `422` |
| `PATCH` | `/api/v1/admin/users/{user_id}/role` | `admin` | `200`, `401`, `403`, `404`, `409`, `422` |
| `PATCH` | `/api/v1/admin/users/{user_id}/status` | `admin` | `200`, `401`, `403`, `404`, `409`, `422` |

**Örnek Kayıt (`POST /api/v1/auth/register`):**
```json
// İstek
{"email": "student@example.edu", "password": "<min-15-char-secret>", "first_name": "Ada", "last_name": "Lovelace"}
// Yanıt (201 Created)
{"id": 1, "email": "student@example.edu", "first_name": "Ada", "last_name": "Lovelace", "role": "student", "is_active": true, "created_at": "2026-11-27T00:00:00Z", "updated_at": "2026-11-27T00:00:00Z"}
```

**Örnek Giriş (`POST /api/v1/auth/login`):**
```json
// İstek
{"email": "student@example.edu", "password": "<min-15-char-secret>"}
// Yanıt (200 OK)
{"access_token": "<jwt-access-token>", "token_type": "bearer", "expires_in": 1800}
```

---

## 13. `DATABASE_DESIGN.md` ile Uygulama Arasındaki Farklar

| # | Konu | Tasarım (Issue #2) | Uygulama (Issue #6) | Tür |
| - | ---- | ------------------ | ------------------- | --- |
| D1 | Uygulanan tablolar | 17 tablo | Yalnızca `users` | Kapsam farkı |
| D2 | E-posta normalizasyonu | Belirtilmemiş | Küçük harf + `CHECK (email = lower(email))` | Eklenen kısıt |
| D3 | E-posta uzunluğu | `VARCHAR(255)` | Kolon aynı; uygulama ≤ 254 karakter kabul eder | Uygulama kuralı |
| D4 | Kısıt adları | Belirtilmemiş | `pk_users`, `uq_users_email`, `ck_users_role`, `ck_users_email_lowercase`, `ix_users_role` | Ekleme |
| D5 | `role` indeksi | Önerilir | `ix_users_role` oluşturuldu | Öneri uygulandı |
| D6 | `role` tipi | `VARCHAR(20)` + `CHECK` | Aynı (`Role(StrEnum)` Python tarafında) | Fark yok |
| D7 | `updated_at` | `DEFAULT NOW()` | `DEFAULT NOW()` + ORM `onupdate`; DB trigger'ı yok | Davranış notu |
| D8 | Parola hash algoritması | `bcrypt` | **Argon2id (`argon2-cffi`)**, PHC formatı (`~97` karakter, `VARCHAR(255)` yeterli); 72 bayt sınırı yok | Tasarımdan sapma |
| D9 | Kullanıcı silme | Belirtilmemiş | Fiziksel silme endpoint'i yok; `is_active=false` soft-disable | Uygulama kuralı |
| D10 | Rol bazlı erişim (§4.3) | Tablo bazlı kurallar | Altyapı hazır; tablo filtreleri Issue #7/#8'i bekliyor | Kısmi |
| D11 | Token / rate limit verisi | — | DB tablosu yok (refresh token yok, rate limit bellekte) | Bilgi |
| D12 | Birincil anahtar | `SERIAL` | `Integer` PK ile PostgreSQL `nextval` (`SERIAL`) doğrulandı | Doğrulandı |
| D13 | PostgreSQL sürümü | `15+` | Testler PostgreSQL `18.1` ile doğrulandı (`15+` uyumlu) | Bilgi |

---

## 14. Testlerin Çalıştırılması ve Doğrulanan Sonuçlar

### 14.1. Veritabanı ve `.env` Olmadan (Unit + API + Baseline)
```bash
cd backend
../.venv/bin/python -m pytest -q
```
- **Doğrulanan sonuç:** `203 passed, 1 skipped, 1 warning` (`56` mevcut baseline + `147` yeni Issue #6 unit/API testi; `tests/integration/conftest.py` `TEST_DATABASE_URL` tanımlı olmadığı için otomatik skip edilir).

### 14.2. İzole PostgreSQL 18.1 Test Container'ı ile Entegrasyon Testleri
```bash
# Yerel postgres:latest imajı (PG 18.1) --pull=never, 127.0.0.1:5433, --tmpfs
docker run --rm -d --pull=never --name studygraph-pg-test \
  -p 127.0.0.1:5433:5432 --tmpfs /var/lib/postgresql \
  -e POSTGRES_USER=studygraph_test \
  -e POSTGRES_PASSWORD="$PG_TEST_PASSWORD" \
  -e POSTGRES_DB=studygraph_test postgres:latest

cd backend
TEST_DATABASE_URL="postgresql+psycopg://studygraph_test:${PG_TEST_PASSWORD}@127.0.0.1:5433/studygraph_test" \
STUDYGRAPH_ALLOW_DESTRUCTIVE_DB_TESTS=1 \
../.venv/bin/python -m pytest -q

docker stop studygraph-pg-test
```
- **Doğrulanan sonuç (Final Review sonrası):** **`214 passed, 0 failed, 0 skipped, 1 warning`** (`203` unit/API + `11` gerçek PostgreSQL 18.1 entegrasyon testi: Alembic upgrade/downgrade/drift, 20 tekrarlı eş zamanlı kayıt, 3×20 tekrarlı eş zamanlı son-admin + negatif kontrol, uçtan uca auth akışı, 4 CLI senaryosu, CLI `--promote-existing` TOCTOU koruması ve Argon2id `needs_rehash` kalıcılık testi).
- Güvenlik riskleri ve üretim öncesi eksikler için bkz. [SECURITY_RISKS.md](SECURITY_RISKS.md).

# StudyGraph AI – Arayüz ve Kullanılabilirlik Testleri (3. Kişi)

## 1. Birim testleri

Komut: `npm.cmd test`, dosya: `src/api/learningLogic.test.js`.
Ek kütüphane gerekmez, Node'un kendi test aracıyla çalışır.

| Test | Sonuç |
|---|---|
| Puan → seviye dönüşümü (eşikler dahil) | Geçti |
| Aynı cevaplar aynı puanı verir (deterministik) | Geçti |
| Örnek grafikte döngü yok | Geçti |
| Döngü oluşturan bağlantı yakalanır | Geçti |
| Topolojik sırada ön koşullar önce gelir | Geçti |
| Dokümandaki senaryo: önce İç İçe Döngüler önerilir | Geçti |
| Ön koşulu eksik ileri konu önerilmez | Geçti |
| Her şey yeterliyse öneri yok | Geçti |
| Tekrar sınavı karar kuralı (0–2 / 3 / 4–5) | Geçti |
| Kolay sınavda tam başarı konuyu "yeterli" yapmaz | Geçti |
| Orta ve zor sınavda puan sınırlanmaz | Geçti |
| İstenen zorlukta ve sayıda soru seçilir, karışıkta dengeli dağılır, soru tekrar etmez | Geçti |
| Backend durum kuralının kopyası (completed / review / study / blocked) | Geçti |
| Backend durumlarından öneri ve engelli konular çıkarılır | Geçti |

**Toplam: 14 test, 14 geçti** (24.11.2026).

Entegrasyon testi (`npm.cmd run test:entegrasyon`): 11 kontrol, hepsi geçti. Ayrıntı: `docs/ENTEGRASYON.md`.

## 2. Arayüz senaryo testleri

Bu senaryolar sahte veri modunda, tarayıcı otomasyonuyla (Chrome) ekranlar tek tek tıklanarak çalıştırıldı.
Konsolda hata çıkmadı.

| # | Senaryo | Beklenen | Sonuç |
|---|---|---|---|
| A1 | Öğrenci olarak giriş | Ders listesi açılır | Geçti |
| A2 | Başlangıç sınavı: 15 soru cevaplanmadan "bitir" | Buton pasif kalır | Geçti |
| A3 | Sınavı bitir | Harita açılır, eksik konular kırmızı, öneri gösterilir | Geçti (öneri: İç İçe Döngüler) |
| A4 | Önerilen konuyu çalış, asistana soru sor | Cevap ve kaynak (not başlığı, sayfa) görünür | Geçti |
| A5 | Tekrar sınavı 5/5 | Puan %33 → %100, "sonraki konuya geç" kararı | Geçti |
| A6 | Güncellenmiş harita | Konu yeşile döner, yeni öneri: Zaman Karmaşıklığı; geçmiş tabloya iki satır | Geçti |
| B1 | Akademisyen yeni ders ekler | Listede "Hazırlanıyor" görünür | Geçti |
| B2 | Kazanım + ön koşul + soru + not eklenir | Ders öğrenciye açılır | Geçti |
| B3 | Öğrenci yeni derste sınav → harita → asistan → tekrar sınavı | Akış yeni dersin verisiyle çalışır | Geçti |
| B4 | Döngü oluşturan ön koşul eklenmeye çalışılır | "Bu bağlantı döngü oluşturur" hatası, eklenmez | Geçti |
| C1 | Yönetici son yöneticinin rolünü değiştirmeye çalışır | "En az bir aktif yönetici kalmalı" hatası | Geçti |
| C2 | Yönetici bir öğrencinin rolünü değiştirir | Rol güncellenir, mesaj çıkar | Geçti |
| D1 | Telefon boyutu (390 px) giriş, ders listesi, harita, tekrar sınavı ayarları | Taşma olmadan görünür | Geçti |
| E1 | Tekrar sınavı ayarı: Kolay + 5 soru (havuzda 3 kolay) | "Bu zorlukta 3 soru var" uyarısı, sınav 3 soruyla açılır | Geçti |
| E2 | Kolay sınavda 3/3 doğru | Puan %69'da sınırlanır, açıklama notu görünür | Geçti |
| E3 | "Farklı ayarlarla tekrar dene" → Karışık + 10 soru, 10/10 | 10 soru gelir, puan %69 → %100, sonraki konu önerilir | Geçti |
| E4 | Ölçüm geçmişi | Satırda zorluk ve soru sayısı yazar | Geçti |
| E5 | Akademisyen soru bankası | Her soruda zorluk etiketi, yeni soruda zorluk seçimi | Geçti |

## 3. Kullanılabilirlik testi (gerçek kullanıcılarla, YAPILACAK)

Henüz gerçek kullanıcılarla yapılmadı. Sunumdan önce 2–3 arkadaşla aşağıdaki görevler denenip tablo doldurulmalı.

| Görev | Kişi 1 | Kişi 2 | Kişi 3 | Gözlem / takıldığı yer |
|---|---|---|---|---|
| Giriş yapıp Algoritma Analizi sınavına başla | | | | |
| Sınavı bitir ve sıradaki önerilen konuyu bul | | | | |
| Haritada bir konunun ön koşullarını bul | | | | |
| Asistana soru sor ve kaynağı göster | | | | |
| Tekrar sınavında zorluk ve soru sayısını kendine göre ayarla, puanın nasıl değiştiğini söyle | | | | |
| (Akademisyen) Yeni ders ve bir soru ekle | | | | |

Her görev için: başarılı mı (Evet/Hayır), yaklaşık süre, kullanıcının kendi yorumu.

## 4. Bilinen sınırlar

- Öğrenme analizi backend'e bağlı ve test edildi; diğer servisler backend'de henüz yok.
- Asistan cevapları demo modunda ders notu parçalarıdır; gerçek yapay zekâ cevabı RAG servisi bağlanınca gelecek.

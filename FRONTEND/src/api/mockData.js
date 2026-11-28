// ------------------------------------------------------------
// ÖRNEK (SAHTE) VERİLER
// Backend hazır olana kadar ekranlar bu verilerle çalışır.
// Proje dokümanındaki "Algoritma Analizi" örnek dersi kullanıldı.
// ------------------------------------------------------------

export const demoUsers = [
  { id: 1, name: 'Demo Öğrenci', email: 'ogrenci@demo.com', role: 'student' },
  { id: 2, name: 'Demo Akademisyen', email: 'akademisyen@demo.com', role: 'instructor' },
  { id: 3, name: 'Demo Yönetici', email: 'yonetici@demo.com', role: 'admin' },
]

// Yönetici ekranındaki kullanıcı listesi (örnek)
export const platformUsers = [
  { id: 1, name: 'Demo Öğrenci', email: 'ogrenci@demo.com', role: 'student', active: true },
  { id: 2, name: 'Demo Akademisyen', email: 'akademisyen@demo.com', role: 'instructor', active: true },
  { id: 3, name: 'Demo Yönetici', email: 'yonetici@demo.com', role: 'admin', active: true },
  { id: 4, name: 'Elif Kaya', email: 'elif.kaya@demo.com', role: 'student', active: true },
  { id: 5, name: 'Mert Demir', email: 'mert.demir@demo.com', role: 'student', active: true },
  { id: 6, name: 'Zeynep Arslan', email: 'zeynep.arslan@demo.com', role: 'student', active: false },
  { id: 7, name: 'Dr. Ayşe Yılmaz', email: 'ayse.yilmaz@demo.com', role: 'instructor', active: true },
]

export const courses = [
  {
    id: 1,
    code: 'BİM201',
    name: 'Algoritma Analizi',
    description: 'Döngüler, karmaşıklık ve sıralama algoritmaları.',
    active: true,
  },
  {
    id: 2,
    code: 'BİM202',
    name: 'Veri Yapıları',
    description: 'Yığın, kuyruk, ağaç ve graf yapıları.',
    active: false, // henüz kazanımları tanımlanmadı
  },
]

// Kazanımlar ve ön koşulları (yönlü grafik)
// prerequisites: bu konuya geçmeden önce bilinmesi gereken konular
export const outcomes = [
  { id: 'k1', name: 'Değişkenler ve Koşullar', prerequisites: [] },
  { id: 'k2', name: 'Diziler', prerequisites: ['k1'] },
  { id: 'k3', name: 'İç İçe Döngüler', prerequisites: ['k1'] },
  { id: 'k4', name: 'Zaman Karmaşıklığı', prerequisites: ['k3'] },
  { id: 'k5', name: 'Bubble Sort', prerequisites: ['k2', 'k3', 'k4'] },
]

// Başlangıç sınavı: her kazanım için 3 soru = 15 soru
export const initialExam = [
  // k1
  { id: 'q1', outcomeId: 'k1', text: 'x = 5 ise "if x > 3" koşulu ne döner?', options: ['True', 'False', 'Hata', '5'], answer: 0 },
  { id: 'q2', outcomeId: 'k1', text: 'Hangisi bir değişkene değer atar?', options: ['x == 4', 'x = 4', 'x != 4', 'x <= 4'], answer: 1 },
  { id: 'q3', outcomeId: 'k1', text: 'a = 2, b = 7 iken "a > 1 and b < 5" sonucu nedir?', options: ['True', 'False', '7', 'Hata'], answer: 1 },
  // k2
  { id: 'q4', outcomeId: 'k2', text: 'A = [4, 8, 15] dizisinde A[1] kaçtır?', options: ['4', '8', '15', 'Hata'], answer: 1 },
  { id: 'q5', outcomeId: 'k2', text: 'n elemanlı bir dizinin son indisi nedir?', options: ['n', 'n + 1', 'n - 1', '0'], answer: 2 },
  { id: 'q6', outcomeId: 'k2', text: 'A = [3, 1, 2] için len(A) kaçtır?', options: ['2', '3', '6', '1'], answer: 1 },
  // k3
  { id: 'q7', outcomeId: 'k3', text: 'for i in range(3): for j in range(2): print() kaç kez yazdırır?', options: ['3', '5', '6', '2'], answer: 2 },
  { id: 'q8', outcomeId: 'k3', text: 'İç içe döngüde iç döngü ne zaman baştan başlar?', options: ['Hiç başlamaz', 'Dış döngünün her adımında', 'Program sonunda', 'Sadece ilk adımda'], answer: 1 },
  { id: 'q9', outcomeId: 'k3', text: 'n x n bir tabloyu gezmek için genelde ne kullanılır?', options: ['Tek if', 'İki iç içe döngü', 'Tek değişken', 'Sadece while True'], answer: 1 },
  // k4
  { id: 'q10', outcomeId: 'k4', text: 'Tek döngüyle n elemanı gezmek hangi karmaşıklıktadır?', options: ['O(1)', 'O(n)', 'O(n²)', 'O(log n)'], answer: 1 },
  { id: 'q11', outcomeId: 'k4', text: 'n\'e kadar giden iki iç içe döngü hangi karmaşıklıktadır?', options: ['O(n)', 'O(2n)', 'O(n²)', 'O(1)'], answer: 2 },
  { id: 'q12', outcomeId: 'k4', text: 'Hangisi n büyüdükçe en yavaş büyür?', options: ['O(n²)', 'O(n)', 'O(n log n)', 'O(log n)'], answer: 3 },
  // k5
  { id: 'q13', outcomeId: 'k5', text: 'Bubble Sort her adımda ne yapar?', options: ['Ortadan böler', 'Komşu elemanları karşılaştırıp yer değiştirir', 'Rastgele seçer', 'Diziyi siler'], answer: 1 },
  { id: 'q14', outcomeId: 'k5', text: 'Bubble Sort\'un en kötü durum karmaşıklığı nedir?', options: ['O(n)', 'O(log n)', 'O(n²)', 'O(1)'], answer: 2 },
  { id: 'q15', outcomeId: 'k5', text: '[3, 1, 2] dizisinde Bubble Sort\'un ilk turu sonunda dizi ne olur?', options: ['[1, 2, 3]', '[1, 3, 2]', '[3, 2, 1]', '[2, 1, 3]'], answer: 0 },
]

// Tekrar sınavı soru havuzu: her kazanım için 10 soru
// difficulty: 'easy' (kolay), 'medium' (orta), 'hard' (zor)
// Öğrenci tekrar sınavında zorluk ve soru sayısını kendisi seçer.
export const retestQuestions = {
  k1: [
    { id: 'r1', difficulty: 'easy', text: 'x = 0 iken "if x:" bloğu çalışır mı?', options: ['Evet', 'Hayır', 'Hata verir', 'Bazen'], answer: 1 },
    { id: 'r2', difficulty: 'easy', text: '"==" operatörü ne yapar?', options: ['Atama', 'Eşitlik karşılaştırması', 'Toplama', 'Döngü'], answer: 1 },
    { id: 'r3', difficulty: 'easy', text: 'y = 10; y = y + 5 sonrası y kaçtır?', options: ['10', '5', '15', '105'], answer: 2 },
    { id: 'r4', difficulty: 'medium', text: '"not True" ifadesinin sonucu nedir?', options: ['True', 'False', 'None', '0'], answer: 1 },
    { id: 'r5', difficulty: 'medium', text: 'elif ne zaman çalışır?', options: ['Her zaman', 'Önceki if yanlışsa ve kendi koşulu doğruysa', 'Hiçbir zaman', 'if doğruysa'], answer: 1 },
    { id: 'r26', difficulty: 'medium', text: 'a = 3; b = a; a = 7 sonrası b kaçtır?', options: ['3', '7', '10', 'Hata'], answer: 0 },
    { id: 'r27', difficulty: 'medium', text: 'x = 15 için "x > 10 or x < 5" sonucu nedir?', options: ['True', 'False', '15', 'Hata'], answer: 0 },
    { id: 'r28', difficulty: 'hard', text: 'x = 5 iken: if x > 3: x = 1 / elif x > 0: x = 2 / else: x = 3. Sonra x kaçtır?', options: ['1', '2', '3', '5'], answer: 0 },
    { id: 'r29', difficulty: 'hard', text: '"not (a > 2 and b < 4)" ifadesinin eşdeğeri hangisidir?', options: ['a > 2 and b < 4', 'a <= 2 or b >= 4', 'a <= 2 and b >= 4', 'a < 2 or b > 4'], answer: 1 },
    { id: 'r30', difficulty: 'hard', text: 'a, b = 1, 2; a, b = b, a sonrası a kaçtır?', options: ['1', '2', '3', 'Hata'], answer: 1 },
  ],
  k2: [
    { id: 'r6', difficulty: 'easy', text: 'A = [5, 6, 7] için A[-1] kaçtır?', options: ['5', '6', '7', 'Hata'], answer: 2 },
    { id: 'r7', difficulty: 'easy', text: 'Diziye sona eleman eklemek için Python\'da ne kullanılır?', options: ['append', 'pop', 'len', 'sort'], answer: 0 },
    { id: 'r9', difficulty: 'easy', text: 'Bir dizinin elemanlarına erişmek için ne kullanılır?', options: ['İndis', 'Koşul', 'Fonksiyon adı', 'Yorum satırı'], answer: 0 },
    { id: 'r8', difficulty: 'medium', text: 'A = [1, 2, 3]; A[0] = 9 sonrası A nedir?', options: ['[1, 2, 3]', '[9, 2, 3]', '[1, 9, 3]', '[9]'], answer: 1 },
    { id: 'r10', difficulty: 'medium', text: '5 elemanlı dizide geçerli indisler hangileridir?', options: ['1–5', '0–4', '0–5', '1–4'], answer: 1 },
    { id: 'r31', difficulty: 'medium', text: 'A = [4, 9, 2] için max(A) kaçtır?', options: ['4', '9', '2', '15'], answer: 1 },
    { id: 'r32', difficulty: 'medium', text: 'A = [1, 2, 3, 4] için A[1:3] nedir?', options: ['[1, 2]', '[2, 3]', '[2, 3, 4]', '[1, 2, 3]'], answer: 1 },
    { id: 'r33', difficulty: 'hard', text: 'A = [1, 2]; B = A; B.append(3) sonrası A nedir?', options: ['[1, 2]', '[1, 2, 3]', '[3]', 'Hata'], answer: 1 },
    { id: 'r34', difficulty: 'hard', text: 'A = [3, 1, 2]; A.pop(0) sonrası A nedir?', options: ['[3, 1]', '[1, 2]', '[3, 2]', '[2]'], answer: 1 },
    { id: 'r35', difficulty: 'hard', text: 'A = [5, 6, 7] için A[len(A)] ne olur?', options: ['7', '5', 'IndexError hatası', '0'], answer: 2 },
  ],
  k3: [
    { id: 'r13', difficulty: 'easy', text: 'Çarpım tablosu (1–9) yazdırmak için en uygun yapı hangisidir?', options: ['Tek if', 'İç içe iki döngü', 'Tek atama', 'Hiçbiri'], answer: 1 },
    { id: 'r15', difficulty: 'easy', text: 'i dış, j iç döngü ise hangisi daha sık değişir?', options: ['i', 'j', 'İkisi eşit', 'Hiçbiri'], answer: 1 },
    { id: 'r11', difficulty: 'easy', text: 'Dış döngü 4, iç döngü 3 kez dönerse iç gövde kaç kez çalışır?', options: ['7', '12', '4', '3'], answer: 1 },
    { id: 'r14', difficulty: 'medium', text: 'İç döngüdeki "break" neyi durdurur?', options: ['Tüm programı', 'Sadece iç döngüyü', 'Sadece dış döngüyü', 'Hiçbir şeyi'], answer: 1 },
    { id: 'r36', difficulty: 'medium', text: 'for i in range(3): for j in range(3): if i == j: print() kaç kez yazdırır?', options: ['3', '6', '9', '1'], answer: 0 },
    { id: 'r37', difficulty: 'medium', text: 'n x m bir matrisin tüm elemanlarını toplamak için iç gövde kaç kez çalışır?', options: ['n + m', 'n × m', 'n', 'm'], answer: 1 },
    { id: 'r38', difficulty: 'medium', text: 'for i in range(1, 4): for j in range(i): ... iç gövde kaç kez çalışır?', options: ['3', '4', '6', '9'], answer: 2 },
    { id: 'r12', difficulty: 'hard', text: 'for i in range(2): for j in range(i): ... iç gövde kaç kez çalışır?', options: ['0', '1', '2', '4'], answer: 1 },
    { id: 'r39', difficulty: 'hard', text: 'for i in range(4): for j in range(i, 4): ... iç gövde kaç kez çalışır?', options: ['4', '8', '10', '16'], answer: 2 },
    { id: 'r40', difficulty: 'hard', text: 's = 0; for i in range(3): for j in range(2): s += i. Sonunda s kaçtır?', options: ['3', '6', '5', '12'], answer: 1 },
  ],
  k4: [
    { id: 'r16', difficulty: 'easy', text: 'Dizide ilk elemana erişmek hangi karmaşıklıktadır?', options: ['O(1)', 'O(n)', 'O(n²)', 'O(log n)'], answer: 0 },
    { id: 'r19', difficulty: 'easy', text: 'Büyük-O gösterimi neyi ifade eder?', options: ['Kod uzunluğunu', 'Girdi büyüdükçe çalışma süresinin büyümesini', 'Değişken sayısını', 'Hata sayısını'], answer: 1 },
    { id: 'r41', difficulty: 'easy', text: 'Tek döngüyle dizideki en büyük elemanı bulmak hangi karmaşıklıktadır?', options: ['O(1)', 'O(n)', 'O(n²)', 'O(n³)'], answer: 1 },
    { id: 'r18', difficulty: 'medium', text: 'Arka arkaya (iç içe değil) iki O(n) döngü toplamda nedir?', options: ['O(n²)', 'O(n)', 'O(1)', 'O(log n)'], answer: 1 },
    { id: 'r20', difficulty: 'medium', text: 'Üç iç içe n\'lik döngü hangi karmaşıklıktadır?', options: ['O(3n)', 'O(n³)', 'O(n²)', 'O(n)'], answer: 1 },
    { id: 'r42', difficulty: 'medium', text: 'O(5n + 20) ifadesi sadeleşince nedir?', options: ['O(5n)', 'O(n)', 'O(20)', 'O(n + 20)'], answer: 1 },
    { id: 'r17', difficulty: 'hard', text: 'Sıralı dizide ikili arama hangi karmaşıklıktadır?', options: ['O(n)', 'O(log n)', 'O(n²)', 'O(1)'], answer: 1 },
    { id: 'r43', difficulty: 'hard', text: 'i = n; while i > 1: i = i // 2 döngüsü hangi karmaşıklıktadır?', options: ['O(n)', 'O(log n)', 'O(n²)', 'O(1)'], answer: 1 },
    { id: 'r44', difficulty: 'hard', text: 'for i in range(n): for j in range(i): ... hangi karmaşıklıktadır?', options: ['O(n)', 'O(n log n)', 'O(n²)', 'O(2n)'], answer: 2 },
    { id: 'r45', difficulty: 'hard', text: 'O(n² + n log n) ifadesinde baskın terim hangisidir?', options: ['n log n', 'n²', 'Eşit', 'log n'], answer: 1 },
  ],
  k5: [
    { id: 'r22', difficulty: 'easy', text: 'Bubble Sort\'ta her turun sonunda en büyük eleman nereye gider?', options: ['Başa', 'Ortaya', 'Sona', 'Silinir'], answer: 2 },
    { id: 'r23', difficulty: 'easy', text: '[2, 1] dizisini sıralamak için kaç yer değiştirme gerekir?', options: ['0', '1', '2', '3'], answer: 1 },
    { id: 'r24', difficulty: 'easy', text: 'Bubble Sort hangi yapıyla yazılır?', options: ['Tek if', 'İç içe döngüler', 'Sadece özyineleme', 'Sözlük'], answer: 1 },
    { id: 'r21', difficulty: 'medium', text: 'Bubble Sort zaten sıralı bir dizide (iyileştirilmiş hâliyle) kaç tur yapar?', options: ['0', '1', 'n', 'n²'], answer: 1 },
    { id: 'r46', difficulty: 'medium', text: '[4, 3, 2, 1] dizisinin ilk turu sonunda dizi ne olur?', options: ['[3, 2, 1, 4]', '[1, 2, 3, 4]', '[3, 4, 2, 1]', '[4, 3, 1, 2]'], answer: 0 },
    { id: 'r47', difficulty: 'medium', text: 'n elemanlı dizide Bubble Sort en fazla kaç tur yapar?', options: ['1', 'n - 1', 'n²', 'log n'], answer: 1 },
    { id: 'r25', difficulty: 'hard', text: 'Bubble Sort kararlı (stable) bir algoritma mıdır?', options: ['Evet', 'Hayır', 'Sadece sayılarda', 'Bilinmez'], answer: 0 },
    { id: 'r48', difficulty: 'hard', text: '[3, 1, 2] dizisinde Bubble Sort toplam kaç yer değiştirme yapar?', options: ['1', '2', '3', '0'], answer: 1 },
    { id: 'r49', difficulty: 'hard', text: 'Bubble Sort\'un en iyi durum karmaşıklığı (erken bitiş kontrolüyle) nedir?', options: ['O(1)', 'O(n)', 'O(n²)', 'O(log n)'], answer: 1 },
    { id: 'r50', difficulty: 'hard', text: '[5, 1, 4, 2] dizisinin ilk turu sonunda dizi ne olur?', options: ['[1, 4, 2, 5]', '[1, 2, 4, 5]', '[1, 5, 4, 2]', '[5, 4, 2, 1]'], answer: 0 },
  ],
}

// Akademisyenin yüklediği ders notlarından parçalar (RAG için)
export const materials = [
  {
    id: 'm1',
    title: 'Hafta 3 Notları – İç İçe Döngüler',
    page: 4,
    outcomeId: 'k3',
    text: 'İç içe döngüde dış döngünün her adımında iç döngü baştan sona çalışır. Dış döngü n, iç döngü m kez dönüyorsa iç gövde toplam n × m kez çalışır.',
  },
  {
    id: 'm2',
    title: 'Hafta 3 Notları – İç İçe Döngüler',
    page: 6,
    outcomeId: 'k3',
    text: 'Örnek: for i in range(3): for j in range(2): print(i, j) çıktısı (0,0) (0,1) (1,0) (1,1) (2,0) (2,1) şeklindedir; toplam 6 satır.',
  },
  {
    id: 'm3',
    title: 'Hafta 4 Notları – Zaman Karmaşıklığı',
    page: 2,
    outcomeId: 'k4',
    text: 'Tek döngü O(n), iç içe iki döngü O(n²) karmaşıklığa sahiptir. Büyük-O, girdi büyüdükçe çalışma süresinin nasıl büyüdüğünü gösterir.',
  },
  {
    id: 'm4',
    title: 'Hafta 5 Notları – Sıralama',
    page: 3,
    outcomeId: 'k5',
    text: 'Bubble Sort komşu elemanları karşılaştırır ve yanlış sıradaysa yer değiştirir. Her turun sonunda en büyük eleman sona yerleşir. En kötü durum O(n²).',
  },
  {
    id: 'm5',
    title: 'Hafta 2 Notları – Diziler',
    page: 1,
    outcomeId: 'k2',
    text: 'Dizi elemanlarına indisle erişilir; ilk indis 0, son indis n - 1 dir. Python listesinde append sona eleman ekler.',
  },
  {
    id: 'm6',
    title: 'Hafta 1 Notları – Değişkenler ve Koşullar',
    page: 2,
    outcomeId: 'k1',
    text: '"=" atama, "==" karşılaştırma operatörüdür. if-elif-else yapısında ilk doğru koşulun bloğu çalışır.',
  },
]

// Akademisyen paneli için örnek sınıf verisi (40 öğrenci, temsili)
export const classReport = {
  studentCount: 40,
  strugglingByOutcome: { k1: 3, k2: 8, k3: 27, k4: 22, k5: 19 },
  // Bireysel ilerleme için örnek öğrenciler (ilk sınav → son durum)
  students: [
    { name: 'Elif Kaya', first: { k1: 100, k2: 67, k3: 33, k4: 0, k5: 33 }, last: { k1: 100, k2: 100, k3: 80, k4: 60, k5: 33 } },
    { name: 'Mert Demir', first: { k1: 67, k2: 67, k3: 33, k4: 33, k5: 0 }, last: { k1: 100, k2: 67, k3: 40, k4: 33, k5: 0 } },
    { name: 'Can Öztürk', first: { k1: 100, k2: 100, k3: 67, k4: 67, k5: 67 }, last: { k1: 100, k2: 100, k3: 100, k4: 80, k5: 80 } },
    { name: 'Selin Aydın', first: { k1: 67, k2: 33, k3: 0, k4: 0, k5: 0 }, last: { k1: 100, k2: 60, k3: 20, k4: 0, k5: 0 } },
    { name: 'Burak Şahin', first: { k1: 100, k2: 100, k3: 33, k4: 33, k5: 33 }, last: { k1: 100, k2: 100, k3: 60, k4: 40, k5: 33 } },
  ],
}

// ------------------------------------------------------------
// ÖĞRENME MANTIĞI (sahte API'nin kullandığı hesaplar)
// Gerçek projede bu hesapları backend (1. kişi) yapar.
// Burada sadece demo çalışsın diye aynı kurallar uygulanıyor.
// ------------------------------------------------------------

// Varsayılan başarı eşikleri (akademisyen panelinden değiştirilebilir)
export const defaultThresholds = { sufficient: 70, developing: 40 }

// Puanı seviyeye çevirir: yeterli / geliştirilmeli / eksik
export function levelOf(score, thresholds = defaultThresholds) {
  if (score === undefined || score === null) return 'unknown'
  if (score >= thresholds.sufficient) return 'sufficient'
  if (score >= thresholds.developing) return 'developing'
  return 'missing'
}

export const levelLabels = {
  sufficient: 'Yeterli',
  developing: 'Geliştirilmeli',
  missing: 'Eksik',
  unknown: 'Ölçülmedi',
}

// Kazanım bazlı puanlama: aynı cevaplar her zaman aynı sonucu verir (deterministik)
export function scoreByOutcome(questions, answers) {
  const totals = {}
  const corrects = {}
  for (const q of questions) {
    totals[q.outcomeId] = (totals[q.outcomeId] || 0) + 1
    if (answers[q.id] === q.answer) {
      corrects[q.outcomeId] = (corrects[q.outcomeId] || 0) + 1
    }
  }
  const scores = {}
  for (const id of Object.keys(totals)) {
    scores[id] = Math.round(((corrects[id] || 0) / totals[id]) * 100)
  }
  return scores
}

// Ön koşul grafiğinde döngü var mı? (A → B → A gibi)
export function hasCycle(outcomes) {
  const state = {} // 0: ziyaret edilmedi, 1: yolda, 2: bitti
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))
  function visit(id) {
    if (state[id] === 1) return true
    if (state[id] === 2) return false
    state[id] = 1
    for (const p of byId[id]?.prerequisites || []) {
      if (visit(p)) return true
    }
    state[id] = 2
    return false
  }
  return outcomes.some((o) => visit(o.id))
}

// Ön koşul sırasına göre dizilmiş kazanımlar (topolojik sıra)
export function topologicalOrder(outcomes) {
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))
  const done = new Set()
  const order = []
  function visit(id) {
    if (done.has(id)) return
    done.add(id)
    for (const p of byId[id].prerequisites) visit(p)
    order.push(byId[id])
  }
  outcomes.forEach((o) => visit(o.id))
  return order
}

// Kişisel öneri: yeterli olmayan ve TÜM ön koşulları yeterli olan ilk konu.
// Böylece ön koşulu eksik olan ileri bir konu asla önerilmez.
export function recommendNext(outcomes, scores, thresholds = defaultThresholds) {
  const ordered = topologicalOrder(outcomes)
  for (const o of ordered) {
    const ok = levelOf(scores[o.id], thresholds) === 'sufficient'
    if (ok) continue
    const prereqsOk = o.prerequisites.every(
      (p) => levelOf(scores[p], thresholds) === 'sufficient',
    )
    if (prereqsOk) {
      const blocked = outcomes
        .filter((x) => x.prerequisites.includes(o.id) && levelOf(scores[x.id], thresholds) !== 'sufficient')
        .map((x) => x.name)
      return { outcome: o, blockedTopics: blocked }
    }
  }
  return null // hepsi yeterli
}

// Tekrar sınavı karar kuralı (dokümandaki örnek kural)
export function retestDecision(correctCount) {
  if (correctCount <= 2) return { type: 'alternative', text: 'Konuyu farklı bir anlatımla tekrar çalışman önerilir.' }
  if (correctCount === 3) return { type: 'practice', text: 'İyi gidiyorsun, birkaç ek alıştırma yapman önerilir.' }
  return { type: 'next', text: 'Harika! Bir sonraki uygun konuya geçebilirsin.' }
}

// ------------------------------------------------------------
// TEKRAR SINAVI AYARLARI (zorluk ve soru sayısı öğrenci tarafından seçilir)
// ------------------------------------------------------------
export const difficultyLabels = { mixed: 'Karışık', easy: 'Kolay', medium: 'Orta', hard: 'Zor' }
export const questionCountOptions = [3, 5, 10]

// Tekrar sınavı puanı: doğru oranı.
// Kural: Sadece kolay sorularla girilen sınav konuyu "yeterli" yapamaz;
// puan en fazla yeterli eşiğinin 1 altına kadar sayılır. Böylece öğrenci
// kolay soru seçerek haritayı yapay olarak yeşile boyayamaz.
export function retestScore(correct, total, difficulty, thresholds = defaultThresholds) {
  const raw = total > 0 ? Math.round((correct / total) * 100) : 0
  if (difficulty === 'easy' && raw >= thresholds.sufficient) {
    return { score: thresholds.sufficient - 1, raw, capped: true }
  }
  return { score: raw, raw, capped: false }
}

// Havuzdan istenen zorlukta ve sayıda soru seçer.
// "Karışık" seçilirse zorluklar dengeli dağıtılır (kolay, orta, zor sırayla).
export function pickQuestions(pool, difficulty, count, random = Math.random) {
  const shuffle = (arr) => {
    const a = [...arr]
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1))
      ;[a[i], a[j]] = [a[j], a[i]]
    }
    return a
  }
  if (difficulty !== 'mixed') {
    return shuffle(pool.filter((q) => (q.difficulty || 'medium') === difficulty)).slice(0, count)
  }
  const groups = ['easy', 'medium', 'hard'].map((d) => shuffle(pool.filter((q) => (q.difficulty || 'medium') === d)))
  const picked = []
  let i = 0
  while (picked.length < count && groups.some((g) => g.length > 0)) {
    const g = groups[i % 3]
    if (g.length > 0) picked.push(g.shift())
    i++
  }
  return picked
}

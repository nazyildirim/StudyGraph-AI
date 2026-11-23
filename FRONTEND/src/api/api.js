// ------------------------------------------------------------
// API KATMANI
// Ekranlar veriyi SADECE bu dosyadaki fonksiyonlardan ister.
//
// USE_MOCK = true  → örnek verilerle çalışır (backend gerekmez)
// USE_MOCK = false → istekler gerçek FastAPI backend'ine gider
//
// Backend hazır olunca: USE_MOCK'u false yap, BASE_URL'i ve
// aşağıdaki yolları (/auth/login vb.) backend'deki gerçek yollarla
// eşleştir. Ekranlarda hiçbir şeyi değiştirmen gerekmez.
// ------------------------------------------------------------

import * as mock from './mockData.js'
import {
  defaultThresholds,
  scoreByOutcome,
  recommendNext,
  retestDecision,
  hasCycle,
  retestScore,
  pickQuestions,
} from './learningLogic.js'

export const USE_MOCK = true
export const BASE_URL = 'http://localhost:8000'

let sessionToken = null

// ---------- Gerçek backend'e istek atan yardımcı ----------
async function request(path, options = {}) {
  const res = await fetch(BASE_URL + path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
      ...(options.headers || {}),
    },
  })
  if (!res.ok) throw new Error(`Sunucu hatası: ${res.status}`)
  return res.json()
}

// ============================================================
// SAHTE VERİ DEPOSU (tarayıcıda saklanır)
// Her dersin kendi kazanımları, soruları ve notları var:
//   store.courses               → ders listesi
//   store.content[dersId]       → kazanımlar, sorular, notlar
//   store.progress[dersId]      → öğrencinin puanları ve geçmişi
//   store.thresholds[dersId]    → başarı eşikleri
// ============================================================
const STORE_KEY = 'studygraph-demo-v4'

function seedStore() {
  // Örnek sorulardaki tekrar sınavı sorularını tek listeye çevir
  const retest = Object.entries(mock.retestQuestions).flatMap(([outcomeId, qs]) =>
    qs.map((q) => ({ ...q, outcomeId, kind: 'retest' })),
  )
  return {
    courses: mock.courses.map(({ active, ...c }) => c),
    content: {
      1: {
        outcomes: mock.outcomes,
        questions: [...mock.initialExam.map((q) => ({ ...q, kind: 'initial', difficulty: 'medium' })), ...retest],
        materials: mock.materials,
      },
      2: { outcomes: [], questions: [], materials: [] },
    },
    progress: {},
    thresholds: {},
    users: mock.platformUsers,
  }
}

function loadStore() {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    // tarayıcı depolaması kullanılamıyorsa baştan başla
  }
  return seedStore()
}
let store = loadStore()

function saveStore() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(store))
  } catch {
    // önemli değil, sadece sayfa yenilenince veri kaybolur
  }
}

const wait = (ms = 200) => new Promise((r) => setTimeout(r, ms))
const content = (courseId) => store.content[courseId]
const progress = (courseId) => {
  store.progress[courseId] = store.progress[courseId] || { scores: {}, history: [] }
  return store.progress[courseId]
}
const thresholdsOf = (courseId) => store.thresholds[courseId] || defaultThresholds
const newId = (prefix) => prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 5)

// Bir ders öğrenciye açılabilir mi? Kazanımı ve başlangıç sorusu olmalı.
function isReady(courseId) {
  const c = content(courseId)
  return c.outcomes.length > 0 && c.questions.some((q) => q.kind === 'initial')
}

// ============================================================
// 1) Oturum açma
// ============================================================
export async function login(email, password, role) {
  if (!USE_MOCK) {
    const data = await request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    sessionToken = data.access_token
    return data.user
  }
  await wait()
  if (!email || !password) throw new Error('E-posta ve şifre gerekli.')
  const user = mock.demoUsers.find((u) => u.role === role)
  return { ...user, email }
}

export function logout() {
  sessionToken = null
}

// ============================================================
// 2) Dersler
// ============================================================
export async function getCourses() {
  if (!USE_MOCK) return request('/courses')
  await wait()
  return store.courses.map((c) => ({
    ...c,
    active: isReady(c.id),
    outcomeCount: content(c.id).outcomes.length,
    questionCount: content(c.id).questions.length,
    materialCount: content(c.id).materials.length,
  }))
}

// Akademisyen yeni ders ekler
export async function createCourse({ code, name, description }) {
  if (!USE_MOCK) {
    return request('/courses', { method: 'POST', body: JSON.stringify({ code, name, description }) })
  }
  await wait()
  if (!code.trim() || !name.trim()) throw new Error('Ders kodu ve adı zorunlu.')
  if (store.courses.some((c) => c.code.toLocaleLowerCase('tr') === code.trim().toLocaleLowerCase('tr'))) {
    throw new Error('Bu ders kodu zaten var.')
  }
  const id = Math.max(0, ...store.courses.map((c) => c.id)) + 1
  const course = { id, code: code.trim(), name: name.trim(), description: description.trim() }
  store.courses.push(course)
  store.content[id] = { outcomes: [], questions: [], materials: [] }
  saveStore()
  return course
}

export async function deleteCourse(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}`, { method: 'DELETE' })
  await wait()
  store.courses = store.courses.filter((c) => c.id !== courseId)
  delete store.content[courseId]
  delete store.progress[courseId]
  saveStore()
}

// ============================================================
// 3) Kazanımlar ve ön koşul grafiği
// ============================================================
export async function getOutcomes(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/outcomes`)
  await wait(100)
  return content(courseId).outcomes
}

export async function addOutcome(courseId, name, prerequisites = []) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/outcomes`, {
      method: 'POST',
      body: JSON.stringify({ name, prerequisite_ids: prerequisites }),
    })
  }
  await wait(100)
  if (!name.trim()) throw new Error('Kazanım adı boş olamaz.')
  const c = content(courseId)
  if (c.outcomes.some((o) => o.name.toLocaleLowerCase('tr') === name.trim().toLocaleLowerCase('tr'))) {
    throw new Error('Bu kazanım zaten var.')
  }
  c.outcomes = [...c.outcomes, { id: newId('k'), name: name.trim(), prerequisites }]
  saveStore()
  return c.outcomes
}

export async function deleteOutcome(courseId, outcomeId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/outcomes/${outcomeId}`, { method: 'DELETE' })
  await wait(100)
  const c = content(courseId)
  c.outcomes = c.outcomes
    .filter((o) => o.id !== outcomeId)
    .map((o) => ({ ...o, prerequisites: o.prerequisites.filter((p) => p !== outcomeId) }))
  c.questions = c.questions.filter((q) => q.outcomeId !== outcomeId)
  saveStore()
  return c.outcomes
}

// Ön koşul bağlantısı ekler (döngü oluşturuyorsa engellenir)
export async function addPrerequisite(courseId, outcomeId, prerequisiteId) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/outcomes/${outcomeId}/prerequisites`, {
      method: 'POST',
      body: JSON.stringify({ prerequisite_id: prerequisiteId }),
    })
  }
  await wait(100)
  if (outcomeId === prerequisiteId) throw new Error('Bir konu kendisinin ön koşulu olamaz.')
  const c = content(courseId)
  const updated = c.outcomes.map((o) =>
    o.id === outcomeId && !o.prerequisites.includes(prerequisiteId)
      ? { ...o, prerequisites: [...o.prerequisites, prerequisiteId] }
      : o,
  )
  if (hasCycle(updated)) throw new Error('Bu bağlantı döngü oluşturur, eklenemez.')
  c.outcomes = updated
  saveStore()
  return updated
}

// ============================================================
// 4) Soru bankası
// kind: 'initial' (başlangıç sınavı) veya 'retest' (tekrar sınavı)
// ============================================================
export async function getQuestions(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/questions`)
  await wait(100)
  return content(courseId).questions
}

export async function addQuestion(courseId, { outcomeId, kind, difficulty = 'medium', text, options, answer }) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/questions`, {
      method: 'POST',
      body: JSON.stringify({ outcome_id: outcomeId, kind, difficulty, text, options, answer }),
    })
  }
  await wait(100)
  if (!outcomeId) throw new Error('Sorunun ölçtüğü kazanımı seç.')
  if (!text.trim()) throw new Error('Soru metni boş olamaz.')
  if (options.some((o) => !o.trim())) throw new Error('Dört seçeneğin hepsini doldur.')
  const c = content(courseId)
  c.questions = [
    ...c.questions,
    { id: newId('q'), outcomeId, kind, difficulty, text: text.trim(), options: options.map((o) => o.trim()), answer },
  ]
  saveStore()
  return c.questions
}

export async function deleteQuestion(courseId, questionId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/questions/${questionId}`, { method: 'DELETE' })
  await wait(100)
  const c = content(courseId)
  c.questions = c.questions.filter((q) => q.id !== questionId)
  saveStore()
  return c.questions
}

// ============================================================
// 5) Ders materyali (RAG için ders notları)
// Gerçek sistemde dosya yüklenir ve backend parçalara böler.
// Demo modunda not metni elle yapıştırılır.
// ============================================================
export async function getMaterials(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/materials`)
  await wait(100)
  return content(courseId).materials
}

export async function addMaterial(courseId, { title, page, outcomeId, text }) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/materials`, {
      method: 'POST',
      body: JSON.stringify({ title, page, outcome_id: outcomeId, text }),
    })
  }
  await wait(100)
  if (!title.trim() || !text.trim()) throw new Error('Başlık ve not metni zorunlu.')
  const c = content(courseId)
  c.materials = [
    ...c.materials,
    { id: newId('m'), title: title.trim(), page: Number(page) || 1, outcomeId, text: text.trim() },
  ]
  saveStore()
  return c.materials
}

export async function deleteMaterial(courseId, materialId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/materials/${materialId}`, { method: 'DELETE' })
  await wait(100)
  const c = content(courseId)
  c.materials = c.materials.filter((m) => m.id !== materialId)
  saveStore()
  return c.materials
}

// ============================================================
// 6) Başlangıç sınavı
// ============================================================
const hideAnswer = ({ answer, ...q }) => q // doğru cevap ekrana gönderilmez

export async function getInitialExam(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/exams/initial`)
  await wait()
  return content(courseId).questions.filter((q) => q.kind === 'initial').map(hideAnswer)
}

export async function submitInitialExam(courseId, answers) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/exams/initial/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    })
  }
  await wait()
  const questions = content(courseId).questions.filter((q) => q.kind === 'initial')
  const scores = scoreByOutcome(questions, answers)
  const p = progress(courseId)
  p.scores = scores
  p.history.push({ date: new Date().toISOString(), type: 'Başlangıç sınavı', scores: { ...scores } })
  saveStore()
  return { scores }
}

// ============================================================
// 7) Öğrenme haritası ve öneri
// ============================================================
export async function getLearningMap(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/learning-map`)
  await wait(100)
  const p = progress(courseId)
  return {
    outcomes: content(courseId).outcomes,
    scores: p.scores,
    thresholds: thresholdsOf(courseId),
    history: p.history,
  }
}

export async function getRecommendation(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/recommendation`)
  await wait(100)
  return recommendNext(content(courseId).outcomes, progress(courseId).scores, thresholdsOf(courseId))
}

// ============================================================
// 8) Tekrar sınavı
// Öğrenci zorluk (mixed/easy/medium/hard) ve soru sayısını seçer.
// ============================================================
function retestPool(courseId, outcomeId) {
  const qs = content(courseId).questions.filter((q) => q.outcomeId === outcomeId)
  const retest = qs.filter((q) => q.kind === 'retest')
  // Tekrar sorusu eklenmemişse o kazanımın başlangıç soruları kullanılır
  return retest.length > 0 ? retest : qs
}

// Ayar ekranı için: her zorlukta kaç soru var?
export async function getRetestOptions(courseId, outcomeId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/outcomes/${outcomeId}/retest/options`)
  await wait(100)
  const pool = retestPool(courseId, outcomeId)
  const count = (d) => pool.filter((q) => (q.difficulty || 'medium') === d).length
  return { mixed: pool.length, easy: count('easy'), medium: count('medium'), hard: count('hard') }
}

export async function getRetest(courseId, outcomeId, { difficulty = 'mixed', count = 5 } = {}) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/outcomes/${outcomeId}/retest?difficulty=${difficulty}&count=${count}`)
  }
  await wait()
  return pickQuestions(retestPool(courseId, outcomeId), difficulty, count).map(hideAnswer)
}

export async function submitRetest(courseId, outcomeId, answers, difficulty = 'mixed') {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/outcomes/${outcomeId}/retest/submit`, {
      method: 'POST',
      body: JSON.stringify({ answers, difficulty }),
    })
  }
  await wait()
  // Sadece öğrenciye sorulan sorular değerlendirilir
  const asked = retestPool(courseId, outcomeId).filter((q) => q.id in answers)
  const correct = asked.filter((q) => answers[q.id] === q.answer).length
  const p = progress(courseId)
  const oldScore = p.scores[outcomeId] ?? 0
  const { score: newScore, raw, capped } = retestScore(correct, asked.length, difficulty, thresholdsOf(courseId))
  p.scores = { ...p.scores, [outcomeId]: newScore }
  p.history.push({
    date: new Date().toISOString(),
    type: 'Tekrar sınavı',
    outcomeId,
    difficulty,
    questionCount: asked.length,
    scores: { ...p.scores },
  })
  saveStore()
  // Karar kuralı 5 soru için tanımlı; farklı soru sayısında orana göre ölçeklenir
  let scaled = Math.round((correct / asked.length) * 5)
  if (capped && scaled >= 4) scaled = 3 // kolay sınavda tam başarı → "ek alıştırma" önerilir
  return { correct, total: asked.length, oldScore, newScore, raw, capped, difficulty, decision: retestDecision(scaled) }
}

// ============================================================
// 9) Yapay zekâ asistanı (RAG)
// Sahte modda: ders notlarında kelime eşleşmesiyle en ilgili
// parçalar bulunur ve kaynaklarıyla birlikte gösterilir.
// Gerçek modda: backend RAG + LLM cevabı döndürür.
// ============================================================
export async function askAssistant(courseId, question, outcomeId) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/assistant`, {
      method: 'POST',
      body: JSON.stringify({ question, outcome_id: outcomeId }),
    })
  }
  await wait(600)
  const words = question
    .toLocaleLowerCase('tr')
    .split(/[^a-zçğıöşü0-9²]+/i)
    .filter((w) => w.length > 2)
  const ranked = content(courseId)
    .materials.map((m) => {
      const text = (m.title + ' ' + m.text).toLocaleLowerCase('tr')
      let score = words.filter((w) => text.includes(w)).length
      if (m.outcomeId === outcomeId) score += 1
      return { m, score }
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 2)
    .map((x) => x.m)

  if (ranked.length === 0) {
    return {
      answer: 'Yüklenen ders notlarında bu soruyla ilgili bir kaynak bulamadım. Soruyu konu adıyla tekrar sorabilir misin?',
      sources: [],
    }
  }
  const answer =
    'Ders notlarına göre:\n\n' +
    ranked.map((m) => '• ' + m.text).join('\n\n') +
    '\n\n(Demo modu: Bu cevap ders notlarından alınan parçalardır. Backend bağlanınca yapay zekâ bu parçaları kullanarak açıklama, örnek ve alıştırma üretecek.)'
  return { answer, sources: ranked.map((m) => ({ title: m.title, page: m.page })) }
}

// ============================================================
// 10) Akademisyen raporları ve ayarları
// ============================================================
export async function getClassReport(courseId) {
  if (!USE_MOCK) return request(`/courses/${courseId}/reports/class`)
  await wait()
  // Örnek sınıf verisi sadece hazır örnek ders için var
  const base = courseId === 1 ? mock.classReport : { studentCount: 0, strugglingByOutcome: {}, students: [] }
  const p = progress(courseId)
  const own = p.history.length
    ? [{ name: 'Demo Öğrenci', first: p.history[0].scores, last: p.scores }]
    : []
  return { ...base, students: [...own, ...base.students] }
}

export async function updateThresholds(courseId, thresholds) {
  if (!USE_MOCK) {
    return request(`/courses/${courseId}/thresholds`, { method: 'PUT', body: JSON.stringify(thresholds) })
  }
  await wait(100)
  store.thresholds[courseId] = thresholds
  saveStore()
  return thresholds
}

// ============================================================
// 11) Platform yöneticisi: kullanıcı ve rol yönetimi
// ============================================================
export async function getUsers() {
  if (!USE_MOCK) return request('/admin/users')
  await wait()
  return store.users
}

export async function updateUser(userId, changes) {
  if (!USE_MOCK) {
    return request(`/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify(changes) })
  }
  await wait(100)
  const target = store.users.find((u) => u.id === userId)
  // Son aktif yöneticinin yetkisi kaldırılamaz (sistem yöneticisiz kalmasın)
  const admins = store.users.filter((u) => u.role === 'admin' && u.active)
  const losesAdmin = (changes.role && changes.role !== 'admin') || changes.active === false
  if (target.role === 'admin' && losesAdmin && admins.length === 1) {
    throw new Error('Sistemde en az bir aktif yönetici kalmalı.')
  }
  store.users = store.users.map((u) => (u.id === userId ? { ...u, ...changes } : u))
  saveStore()
  return store.users
}

export async function addUser({ name, email, role }) {
  if (!USE_MOCK) return request('/admin/users', { method: 'POST', body: JSON.stringify({ name, email, role }) })
  await wait(100)
  if (!name.trim() || !email.trim()) throw new Error('Ad ve e-posta zorunlu.')
  if (store.users.some((u) => u.email.toLowerCase() === email.trim().toLowerCase())) {
    throw new Error('Bu e-posta zaten kayıtlı.')
  }
  const id = Math.max(0, ...store.users.map((u) => u.id)) + 1
  store.users = [...store.users, { id, name: name.trim(), email: email.trim(), role, active: true }]
  saveStore()
  return store.users
}

// Demo verisini sıfırlar (sunumdan önce temiz başlamak için)
export function resetDemo() {
  try {
    localStorage.removeItem(STORE_KEY)
  } catch {
    // yoksay
  }
  store = seedStore()
}

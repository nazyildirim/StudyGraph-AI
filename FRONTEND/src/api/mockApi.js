// ------------------------------------------------------------
// DEMO MODU (örnek veri)
// Backend çalışmadan sunum yapılabilsin diye tüm servisler burada
// örnek veriyle taklit edilir. Canlı mod için bkz. liveApi.js.
// Seçim api.js içinde yapılır (VITE_USE_MOCK).
//
// Demo modunda bile harita analizi, backend açıksa Ranya'nın
// POST /api/v1/learning-analyses servisinden alınır; kapalıysa
// aynı kurallarla tarayıcıda hesaplanır.
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
  statusesFromScores,
  recommendationFromStatuses,
} from './learningLogic.js'

// Öğrenme analizi servisinin adresi. Geliştirmede Vite, /api isteklerini
// http://localhost:8000 adresine yönlendirir (vite.config.js).
const ENV = import.meta.env || {}
let ANALYSIS_URL = ENV.VITE_ANALYSIS_URL || '/api/v1'
export function setAnalysisUrl(url) {
  ANALYSIS_URL = url // testlerde kullanılır
}

// ============================================================
// SAHTE VERİ DEPOSU (tarayıcıda saklanır)
// Her dersin kendi kazanımları, soruları ve notları var:
//   store.courses               → ders listesi
//   store.content[dersId]       → kazanımlar, sorular, notlar
//   store.progress[dersId]      → öğrencinin puanları ve geçmişi
//   store.thresholds[dersId]    → başarı eşikleri
// ============================================================
const STORE_KEY = 'studygraph-demo-v5'

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
  // results: kazanım başına en son ölçümün soru sonuçları (backend'e gider)
  // capped: son ölçümü "kolay sınav sınırına" takılan kazanımlar
  store.progress[courseId] = store.progress[courseId] || { scores: {}, history: [], results: {}, capped: {} }
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
  await wait()
  if (!email || !password) throw new Error('E-posta ve şifre gerekli.')
  const user = mock.demoUsers.find((u) => u.role === role)
  return { ...user, email }
}

export function logout() {}

// ============================================================
// 2) Dersler
// ============================================================
export async function getCourses() {
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
  await wait(100)
  return content(courseId).outcomes
}

export async function addOutcome(courseId, name, prerequisites = []) {
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
  await wait(100)
  return content(courseId).questions
}

export async function addQuestion(courseId, { outcomeId, kind, difficulty = 'medium', text, options, answer }) {
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
  await wait(100)
  return content(courseId).materials
}

export async function addMaterial(courseId, { title, page, outcomeId, text }) {
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
  await wait()
  return content(courseId).questions.filter((q) => q.kind === 'initial').map(hideAnswer)
}

export async function submitInitialExam(courseId, answers) {
  await wait()
  const questions = content(courseId).questions.filter((q) => q.kind === 'initial')
  const scores = scoreByOutcome(questions, answers)
  const p = progress(courseId)
  p.scores = scores
  p.results = {}
  p.capped = {}
  for (const q of questions) {
    p.results[q.outcomeId] = p.results[q.outcomeId] || []
    // Doğru/yanlış sınav sisteminde (şimdilik bu katmanda) belirlenir, tarayıcıdan gelmez
    p.results[q.outcomeId].push({ question_id: q.id, outcome_id: q.outcomeId, is_correct: answers[q.id] === q.answer })
  }
  p.history.push({ date: new Date().toISOString(), type: 'Başlangıç sınavı', scores: { ...scores } })
  saveStore()
  return { scores }
}

// ============================================================
// 7) Öğrenme haritası ve öneri  →  RANYA'NIN BACKEND'İ
// ============================================================

// Backend'e gidecek isteği sözleşmedeki formatta hazırlar
export function buildAnalysisRequest(courseId) {
  const c = content(courseId)
  const p = progress(courseId)
  const question_results = Object.values(p.results || {}).flat()
  if (question_results.length === 0) return null
  return {
    course_id: String(courseId),
    outcomes: c.outcomes.map((o) => ({ id: o.id, course_id: String(courseId), title: o.name })),
    prerequisite_edges: c.outcomes.flatMap((o) =>
      o.prerequisites.map((pre) => ({ outcome_id: o.id, prerequisite_id: pre })),
    ),
    question_results,
    mastery_threshold: thresholdsOf(courseId).sufficient,
  }
}

// Backend'den analiz ister. Ulaşılamazsa null döner (yerel hesaba geçilir).
async function analyzeWithBackend(courseId) {
  const body = buildAnalysisRequest(courseId)
  if (!body) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 2500)
  try {
    const res = await fetch(`${ANALYSIS_URL}/learning-analyses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!res.ok) {
      console.warn('Öğrenme analizi servisi hata döndürdü:', res.status, await res.text())
      return null
    }
    const data = await res.json()
    const c = content(courseId)
    const p = progress(courseId)
    const threshold = thresholdsOf(courseId).sufficient
    const scores = Object.fromEntries(data.scores.map((s) => [s.outcome_id, Math.round(s.score_percent)]))
    let statuses = Object.fromEntries(
      data.recommendations.map((r) => [r.outcome_id, { status: r.status, missing: [...r.missing_prerequisites] }]),
    )
    // Kolay sınav sınırı: backend zorluk bilgisini almadığı için burada uygulanır
    let cappedAny = false
    for (const id of Object.keys(p.capped || {})) {
      if (p.capped[id] && scores[id] >= threshold) {
        scores[id] = threshold - 1
        cappedAny = true
      }
    }
    if (cappedAny) statuses = statusesFromScores(c.outcomes, scores, threshold, data.learning_order)
    return { scores, statuses, learningOrder: data.learning_order }
  } catch {
    return null // backend kapalı ya da yanıt vermedi
  } finally {
    clearTimeout(timer)
  }
}

export async function getLearningMap(courseId) {
  const p = progress(courseId)
  const base = { outcomes: content(courseId).outcomes, thresholds: thresholdsOf(courseId), history: p.history }
  const analysis = await analyzeWithBackend(courseId)
  if (analysis) {
    return { ...base, scores: analysis.scores, statuses: analysis.statuses, analysisSource: 'backend' }
  }
  await wait(100)
  return { ...base, scores: p.scores, analysisSource: 'local' }
}

export async function getRecommendation(courseId) {
  const c = content(courseId)
  const analysis = await analyzeWithBackend(courseId)
  if (analysis) return recommendationFromStatuses(c.outcomes, analysis.statuses, analysis.learningOrder)
  await wait(100)
  return recommendNext(c.outcomes, progress(courseId).scores, thresholdsOf(courseId))
}

// Backend çalışıyor mu? (harita ekranındaki küçük gösterge için)
export async function checkBackendHealth() {
  try {
    const res = await fetch(`${ANALYSIS_URL}/health`)
    return res.ok
  } catch {
    return false
  }
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
  await wait(100)
  const pool = retestPool(courseId, outcomeId)
  const count = (d) => pool.filter((q) => (q.difficulty || 'medium') === d).length
  return { mixed: pool.length, easy: count('easy'), medium: count('medium'), hard: count('hard') }
}

export async function getRetest(courseId, outcomeId, { difficulty = 'mixed', count = 5 } = {}) {
  await wait()
  return pickQuestions(retestPool(courseId, outcomeId), difficulty, count).map(hideAnswer)
}

export async function submitRetest(courseId, outcomeId, answers, difficulty = 'mixed') {
  await wait()
  // Sadece öğrenciye sorulan sorular değerlendirilir
  const asked = retestPool(courseId, outcomeId).filter((q) => q.id in answers)
  const correct = asked.filter((q) => answers[q.id] === q.answer).length
  const p = progress(courseId)
  const oldScore = p.scores[outcomeId] ?? 0
  const { score: newScore, raw, capped } = retestScore(correct, asked.length, difficulty, thresholdsOf(courseId))
  p.scores = { ...p.scores, [outcomeId]: newScore }
  p.results = { ...p.results, [outcomeId]: asked.map((q) => ({ question_id: q.id, outcome_id: outcomeId, is_correct: answers[q.id] === q.answer })) }
  p.capped = { ...p.capped, [outcomeId]: capped }
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
  await wait(100)
  store.thresholds[courseId] = thresholds
  saveStore()
  return thresholds
}

// ============================================================
// 11) Platform yöneticisi: kullanıcı ve rol yönetimi
// ============================================================
export async function getUsers() {
  await wait()
  return store.users
}

export async function updateUser(userId, changes) {
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

// Demo modunda hangi özellikler kullanılabilir (ekranlar buna göre form gösterir)
export const features = {
  mode: 'demo',
  roleSelect: true, // girişte rol seçimi (canlıda rol sunucudan gelir)
  register: false,
  manageCourses: true,
  manageOutcomes: true,
  questionKinds: true, // soruyu başlangıç/tekrar sınavı diye ayırma
  editQuestion: false,
  materialText: true,
  materialUpload: false,
  classReport: true,
  editThresholds: true,
  addUser: true,
  retestPoolCounts: true,
  easyCap: true,
  assistantModes: false,
}

// Canlı moda özgü işlemler (demo modunda kullanılmaz)
export async function register() {
  throw new Error('Demo modunda kayıt yok; herhangi bir e-posta ve şifreyle giriş yapabilirsin.')
}
export async function uploadMaterial() {
  throw new Error('Demo modunda dosya yükleme yok; not metnini yapıştırabilirsin.')
}
export async function updateQuestion() {
  throw new Error('Demo modunda soru düzenleme yok.')
}

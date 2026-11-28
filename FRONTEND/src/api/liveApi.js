// ------------------------------------------------------------
// CANLI MOD: ekibin FastAPI backend'i
// Sözleşmeler: docs/AUTHENTICATION.md, docs/ASSESSMENT_API_CONTRACT.md,
//              docs/RAG_API_CONTRACT.md (backend dalları)
//
// Ekranlar demo modundaki veri biçimini kullanır. Bu dosya backend'in
// yanıtlarını o biçime çevirir; böylece ekranlar iki modda da aynı çalışır.
//   - Kimlikler ekranda metin ("3"), backend'e sayı (3) olarak gider.
//   - Sınav sorularında şık sırası ↔ option_id eşlemesi burada tutulur;
//     doğru cevap tarayıcıya hiç gelmez, puanlama sunucuda yapılır.
//   - Token sadece bellekte tutulur (localStorage'a yazılmaz).
// ------------------------------------------------------------
import { retestDecision } from './learningLogic.js'
import { LIVE_COURSES } from '../config.js'

const ENV = import.meta.env || {}
let API = ENV.VITE_API_URL || '/api/v1'
export function setApiUrl(url) {
  API = url // testlerde kullanılır
}

// Backend'de ders listeleme servisi henüz yok; dersler src/config.js dosyasından okunur.
function configuredCourses() {
  return LIVE_COURSES.length ? LIVE_COURSES : [{ id: 1, code: 'DERS-1', name: 'Ders 1', description: '' }]
}

export const features = {
  mode: 'live',
  roleSelect: false,
  register: true,
  manageCourses: false, // backend'de ders oluşturma servisi yok
  manageOutcomes: false, // backend'de kazanım ekleme servisi yok (sadece okuma)
  questionKinds: false, // backend aynı soru havuzunu iki sınavda da kullanır
  editQuestion: true,
  materialText: true,
  materialUpload: true,
  classReport: false, // backend'de sınıf raporu servisi yok
  editThresholds: false, // eşik backend ayarı (70)
  addUser: false, // kullanıcılar kendileri kayıt olur
  retestPoolCounts: false, // öğrenci soru havuzunu göremez
  easyCap: false, // puanlama tamamen sunucuda; zorluk tavanı uygulanmaz
  assistantModes: true,
}

// ---------- Oturum ----------
let token = null
let currentUser = null

export class ApiError extends Error {
  constructor(status, message, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function friendly(status, detail) {
  if (typeof detail === 'string' && detail && status !== 500) return detail
  return (
    {
      400: 'İstek geçersiz.',
      401: 'Oturumun sona erdi, lütfen tekrar giriş yap.',
      403: 'Bu işlem için yetkin yok.',
      404: 'Kayıt bulunamadı ya da bu derse erişimin yok.',
      409: 'İşlem şu an yapılamıyor (çakışma).',
      413: 'Dosya çok büyük (en fazla 10 MB).',
      415: 'Sadece PDF ve TXT dosyaları yüklenebilir.',
      422: 'Girilen bilgilerde hata var.',
      429: 'Çok fazla deneme yapıldı, biraz bekleyip tekrar dene.',
      503: 'Servis şu an meşgul ya da kapalı, biraz sonra tekrar dene.',
    }[status] || `Sunucu hatası (${status}).`
  )
}

async function call(path, { method = 'GET', body, form, timeout = 20000, auth = true } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  let res
  try {
    res = await fetch(API + path, {
      method,
      signal: controller.signal,
      headers: {
        ...(form ? {} : { 'Content-Type': 'application/json' }), // FormData'da tarayıcı kendisi ekler
        ...(auth && token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: form || (body !== undefined ? JSON.stringify(body) : undefined),
    })
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError(0, 'Sunucu zamanında yanıt vermedi.')
    throw new ApiError(0, "Backend'e ulaşılamıyor. Sunucu çalışıyor mu?")
  } finally {
    clearTimeout(timer)
  }
  if (res.status === 204) return null
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data?.detail
    if (res.status === 401 && auth && token) {
      token = null
      currentUser = null
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('studygraph:unauthorized'))
    }
    const msg = Array.isArray(detail) ? friendly(res.status) : friendly(res.status, detail)
    throw new ApiError(res.status, msg, detail)
  }
  return data
}

const fullName = (u) => [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email

export async function login(email, password) {
  if (!email || !password) throw new Error('E-posta ve şifre gerekli.')
  try {
    const t = await call('/auth/login', { method: 'POST', body: { email, password }, auth: false })
    token = t.access_token
  } catch (err) {
    if (err.status === 401) throw new Error('E-posta ya da şifre hatalı.')
    throw err
  }
  const me = await call('/users/me')
  currentUser = { id: me.id, name: fullName(me), email: me.email, role: me.role }
  return currentUser
}

export async function register({ email, password, firstName, lastName }) {
  if (!email || !password || !firstName || !lastName) throw new Error('Tüm alanları doldur.')
  try {
    await call('/auth/register', {
      method: 'POST',
      body: { email, password, first_name: firstName, last_name: lastName },
      auth: false,
    })
  } catch (err) {
    if (err.status === 409) throw new Error('Bu e-posta ile kayıtlı bir hesap var.')
    if (err.status === 422) throw new Error('Bilgileri kontrol et (şifre yeterince uzun olmalı, e-posta geçerli olmalı).')
    throw err
  }
  return login(email, password)
}

export function logout() {
  token = null
  currentUser = null
  attempts.clear()
}

// ---------- Dersler ----------
export async function getCourses() {
  return configuredCourses().map((c) => ({ ...c, active: true, outcomeCount: null, questionCount: null, materialCount: null }))
}
const notAvailable = (what) => async () => {
  throw new Error(`Backend'de ${what} servisi henüz yok.`)
}
export const createCourse = notAvailable('ders oluşturma')
export const deleteCourse = notAvailable('ders silme')

// ---------- Kazanımlar ----------
const toOutcome = (o) => ({
  id: String(o.id),
  code: o.code,
  name: o.title,
  prerequisites: (o.prerequisite_ids || []).map(String),
})

export async function getOutcomes(courseId) {
  const list = await call(`/courses/${courseId}/outcomes`)
  return list.sort((a, b) => a.order_index - b.order_index).map(toOutcome)
}
export const addOutcome = notAvailable('kazanım ekleme')
export const deleteOutcome = notAvailable('kazanım silme')
export const addPrerequisite = notAvailable('ön koşul ekleme')

// ---------- Soru bankası (akademisyen) ----------
const toQuestion = (q) => {
  const opts = [...q.options].sort((a, b) => a.order_index - b.order_index)
  return {
    id: String(q.id),
    outcomeId: String(q.learning_outcome_id),
    kind: 'bank',
    difficulty: q.difficulty_level,
    text: q.question_text,
    options: opts.map((o) => o.option_text),
    answer: opts.findIndex((o) => o.is_correct),
    version: q.version_number,
  }
}

export async function getQuestions(courseId) {
  const all = []
  for (let offset = 0; offset < 1000; offset += 100) {
    const page = await call(`/courses/${courseId}/questions?limit=100&offset=${offset}`)
    all.push(...page)
    if (page.length < 100) break
  }
  return all.map(toQuestion)
}

function questionBody({ outcomeId, difficulty = 'medium', text, options, answer }) {
  if (!outcomeId) throw new Error('Sorunun ölçtüğü kazanımı seç.')
  if (!text?.trim()) throw new Error('Soru metni boş olamaz.')
  if (options.some((o) => !o.trim())) throw new Error('Dört seçeneğin hepsini doldur.')
  return {
    learning_outcome_id: Number(outcomeId),
    question_text: text.trim(),
    difficulty_level: difficulty,
    options: options.map((o, i) => ({ option_text: o.trim(), is_correct: i === answer, order_index: i })),
  }
}

export async function addQuestion(courseId, form) {
  await call(`/courses/${courseId}/questions`, { method: 'POST', body: questionBody(form) })
  return getQuestions(courseId)
}

export async function updateQuestion(courseId, questionId, form) {
  const res = await call(`/courses/${courseId}/questions/${questionId}`, { method: 'PUT', body: questionBody(form) })
  return { questions: await getQuestions(courseId), versioned: res.was_versioned }
}

export async function deleteQuestion(courseId, questionId) {
  const res = await call(`/courses/${courseId}/questions/${questionId}`, { method: 'DELETE' })
  const questions = await getQuestions(courseId)
  questions.lastDeleteArchived = res?.archived === true
  return questions
}

// ---------- Ders materyalleri (RAG) ----------
const statusLabel = { processed: 'İşlendi', failed: 'İşlenemedi', pending: 'İşleniyor', processing: 'İşleniyor' }
const toMaterial = (m) => ({
  id: String(m.id),
  title: m.title,
  page: m.page,
  outcomeId: m.outcomeId || '',
  fileType: m.file_type,
  status: m.processing_status,
  statusLabel: statusLabel[m.processing_status] || m.processing_status,
  error: m.error_message,
  pageCount: m.page_count,
})

export async function getMaterials(courseId) {
  return (await call(`/courses/${courseId}/materials`)).map(toMaterial)
}

export async function addMaterial(courseId, { title, page, outcomeId, text }) {
  if (!title?.trim() || !text?.trim()) throw new Error('Başlık ve not metni zorunlu.')
  await call(`/courses/${courseId}/materials`, {
    method: 'POST',
    body: { title: title.trim(), text: text.trim(), page: Number(page) || 1, outcome_id: outcomeId || null },
    timeout: 120000,
  })
  return getMaterials(courseId)
}

export async function uploadMaterial(courseId, { file, title, outcomeId }) {
  if (!file) throw new Error('Bir PDF ya da TXT dosyası seç.')
  const form = new FormData()
  form.append('file', file)
  if (title?.trim()) form.append('title', title.trim())
  if (outcomeId) form.append('outcome_id', outcomeId)
  const m = await call(`/courses/${courseId}/materials/upload`, { method: 'POST', form, timeout: 180000 })
  const list = await getMaterials(courseId)
  list.lastUpload = toMaterial(m)
  return list
}

export async function deleteMaterial(courseId, materialId) {
  await call(`/courses/${courseId}/materials/${materialId}`, { method: 'DELETE' })
  return getMaterials(courseId)
}

// ---------- Sınavlar ----------
// Her sınav oturumu için: soru kimliği → şıkların option_id listesi
const attempts = new Map()

function rememberAttempt(exam) {
  const questions = [...exam.questions].sort((a, b) => a.order_index - b.order_index)
  attempts.set(exam.course_id + ':' + exam.attempt_id, {
    optionIds: Object.fromEntries(
      questions.map((q) => [String(q.question_id), [...q.options].sort((a, b) => a.order_index - b.order_index).map((o) => o.option_id)]),
    ),
  })
  const list = questions.map((q) => ({
    id: String(q.question_id),
    outcomeId: String(q.learning_outcome_id),
    difficulty: q.difficulty_level,
    text: q.question_text,
    options: [...q.options].sort((a, b) => a.order_index - b.order_index).map((o) => o.option_text),
  }))
  list.attemptId = exam.attempt_id
  list.resumed = exam.resumed
  list.unseen = exam.unseen_question_count
  list.reused = exam.reused_question_count
  return list
}

function answersBody(courseId, attemptId, answers) {
  const a = attempts.get(courseId + ':' + attemptId)
  if (!a) throw new Error('Sınav oturumu bulunamadı, sayfayı yenileyip tekrar dene.')
  return {
    answers: Object.entries(a.optionIds).map(([qid, optionIds]) => ({
      question_id: Number(qid),
      selected_option_id: answers[qid] === undefined ? null : optionIds[answers[qid]],
    })),
  }
}

// Backend'in 409 mesajları (exam_generation_service.py) → Türkçe açıklama
const examMessages = [
  [/already been completed/i, 'Başlangıç sınavını zaten tamamladın. Haritana bakabilirsin.'],
  [/No learning outcomes or active questions|No active questions are available/i, 'Bu derste henüz sınav sorusu yok. Akademisyenin soru eklemesi gerekiyor.'],
  [/No active questions match/i, 'Bu konu ve zorluk için soru havuzunda soru yok. Zorluğu "Karışık" yapıp tekrar dene.'],
  [/must be completed before starting a retest/i, 'Önce başlangıç sınavını tamamlaman gerekiyor.'],
  [/not eligible for retest/i, 'Bu konu için şu an tekrar sınavı açılamıyor: konu tamamlanmış, ön koşulları eksik ya da henüz ölçülmemiş olabilir.'],
  [/No weak, unblocked/i, 'Tekrar sınavı gereken konu kalmadı.'],
  [/in-progress review exam already exists/i, 'Yarım kalmış başka bir tekrar sınavın var.'],
]
function examError(err) {
  if (err.status !== 409) return err
  const text = typeof err.detail === 'string' ? err.detail : ''
  const hit = examMessages.find(([re]) => re.test(text))
  return new ApiError(409, hit ? hit[1] : err.message, err.detail)
}

export async function getInitialExam(courseId) {
  try {
    const exam = await call(`/courses/${courseId}/exams/initial`, { method: 'POST', body: {} })
    return rememberAttempt(exam)
  } catch (err) {
    throw examError(err)
  }
}

export async function submitInitialExam(courseId, answers, attemptId) {
  const res = await call(`/courses/${courseId}/exams/attempts/${attemptId}/submit`, {
    method: 'POST',
    body: answersBody(courseId, attemptId, answers),
  })
  attempts.delete(courseId + ':' + attemptId)
  return res
}

// Öğrenci soru havuzunu göremediği için zorluk başına soru sayısı bilinmiyor
export async function getRetestOptions() {
  return { mixed: null, easy: null, medium: null, hard: null }
}

export async function getRetest(courseId, outcomeId, { difficulty = 'mixed', count = 5 } = {}) {
  const body = { learning_outcome_id: Number(outcomeId), question_count: count }
  if (difficulty !== 'mixed') body.difficulty = difficulty
  try {
    return rememberAttempt(await call(`/courses/${courseId}/exams/retest`, { method: 'POST', body }))
  } catch (err) {
    // Farklı ayarlarla yarım kalmış tekrar sınavı varsa onu bulup kaldığı yerden aç
    if (err.status === 409 && /in-progress review exam already exists/i.test(String(err.detail))) {
      const history = await call(`/courses/${courseId}/exams/history?limit=50`)
      const open = history.find((h) => h.assessment_type === 'retest' && h.status === 'in_progress')
      if (open) {
        const exam = rememberAttempt(await call(`/courses/${courseId}/exams/attempts/${open.attempt_id}`))
        exam.resumed = true
        exam.differentSettings = true
        exam.outcomeIds = [...new Set(exam.map((q) => q.outcomeId))]
        return exam
      }
    }
    throw examError(err)
  }
}

export async function submitRetest(courseId, outcomeId, answers, difficulty = 'mixed', attemptId) {
  const before = await masteryScores(courseId)
  const res = await call(`/courses/${courseId}/exams/attempts/${attemptId}/submit`, {
    method: 'POST',
    body: answersBody(courseId, attemptId, answers),
  })
  attempts.delete(courseId + ':' + attemptId)
  const after = await masteryScores(courseId)
  // Devam ettirilen sınav başka bir konuya aitse tüm sonuçlar kullanılır
  const matching = res.results.filter((r) => String(r.learning_outcome_id) === String(outcomeId))
  const mine = matching.length ? matching : res.results
  const correct = mine.filter((r) => r.is_correct).length
  const total = mine.length
  return {
    correct,
    total,
    oldScore: before[outcomeId] ?? 0,
    newScore: after[outcomeId] ?? Math.round(res.score),
    raw: Math.round(res.score),
    capped: false,
    difficulty,
    decision: retestDecision(Math.round((correct / Math.max(total, 1)) * 5)),
  }
}

// ---------- Öğrenme haritası ve öneriler ----------
async function masteryScores(courseId) {
  const m = await call(`/courses/${courseId}/mastery`)
  return Object.fromEntries(
    m.outcomes.filter((o) => o.is_assessed && o.mastery_score !== null).map((o) => [String(o.learning_outcome_id), Math.round(o.mastery_score)]),
  )
}

function perOutcome(results) {
  const acc = {}
  for (const r of results) {
    const k = String(r.learning_outcome_id)
    acc[k] = acc[k] || [0, 0]
    acc[k][1]++
    if (r.is_correct) acc[k][0]++
  }
  return Object.fromEntries(Object.entries(acc).map(([k, [c, t]]) => [k, Math.round((c / t) * 100)]))
}

const typeLabel = { diagnostic: 'Başlangıç sınavı', retest: 'Tekrar sınavı' }

async function examHistory(courseId) {
  const items = await call(`/courses/${courseId}/exams/history?limit=50`)
  const done = items.filter((h) => h.status === 'completed').reverse() // eskiden yeniye
  const rows = []
  for (const h of done) {
    const r = await call(`/courses/${courseId}/exams/attempts/${h.attempt_id}/result`)
    const scores = perOutcome(r.results)
    const ids = Object.keys(scores)
    rows.push({
      date: h.completed_at || h.started_at,
      type: typeLabel[h.assessment_type] || h.title,
      outcomeId: h.assessment_type === 'retest' && ids.length === 1 ? ids[0] : undefined,
      questionCount: r.total_questions,
      scores,
    })
  }
  return rows
}

export async function getLearningMap(courseId) {
  const [outcomes, mastery, recs, history] = await Promise.all([
    getOutcomes(courseId),
    call(`/courses/${courseId}/mastery`),
    call(`/courses/${courseId}/recommendations`),
    examHistory(courseId),
  ])
  const scores = Object.fromEntries(
    mastery.outcomes.filter((o) => o.is_assessed && o.mastery_score !== null).map((o) => [String(o.learning_outcome_id), Math.round(o.mastery_score)]),
  )
  const statuses = Object.fromEntries(
    recs.recommendations.map((r) => [String(r.learning_outcome_id), { status: r.status, missing: r.missing_prerequisites.map(String), reason: r.reason }]),
  )
  return {
    outcomes,
    scores,
    statuses,
    thresholds: { sufficient: mastery.mastery_threshold, developing: 40 },
    history,
    analysisSource: 'backend',
  }
}

export async function getRecommendation(courseId) {
  const [outcomes, recs] = await Promise.all([getOutcomes(courseId), call(`/courses/${courseId}/recommendations`)])
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))
  const ordered = [...recs.recommendations].sort((a, b) => a.priority_order - b.priority_order)
  const next = ordered.find((r) => r.status === 'review' || r.status === 'study')
  if (!next) return null
  const id = String(next.learning_outcome_id)
  return {
    outcome: byId[id],
    reason: next.reason,
    blockedTopics: ordered
      .filter((r) => r.status === 'blocked' && r.missing_prerequisites.map(String).includes(id))
      .map((r) => byId[String(r.learning_outcome_id)]?.name)
      .filter(Boolean),
  }
}

export async function checkBackendHealth() {
  try {
    await call('/health', { auth: false, timeout: 3000 })
    return true
  } catch {
    return false
  }
}

// ---------- Yapay zekâ asistanı ----------
export async function askAssistant(courseId, question, outcomeId, mode = 'topic_explanation') {
  const res = await call(`/courses/${courseId}/assistant`, {
    method: 'POST',
    body: { question, mode, outcome_id: outcomeId ? String(outcomeId) : null },
    timeout: 90000, // yerel model ilk istekte ~30 sn sürebilir
  })
  return {
    answer: res.answer,
    sources: res.sources.map((s) => ({
      id: s.source_id,
      title: s.title,
      page: s.page_start && s.page_end && s.page_start !== s.page_end ? `${s.page_start}–${s.page_end}` : s.page ?? s.page_start,
    })),
    grounded: res.grounded,
    fallback: res.fallback_used,
    model: res.model_name,
  }
}

// ---------- Raporlar ve eşikler ----------
export async function getClassReport() {
  return { studentCount: 0, strugglingByOutcome: {}, students: [], unavailable: true }
}
export const updateThresholds = notAvailable('başarı eşiği ayarlama')

// ---------- Yönetici ----------
const toUser = (u) => ({ id: u.id, name: fullName(u), email: u.email, role: u.role, active: u.is_active })

export async function getUsers() {
  const all = []
  for (let offset = 0; offset < 2000; offset += 100) {
    const page = await call(`/admin/users?limit=100&offset=${offset}`)
    all.push(...page.items)
    if (all.length >= page.total || page.items.length === 0) break
  }
  return all.map(toUser)
}

export async function updateUser(userId, changes) {
  try {
    if (changes.role !== undefined) {
      await call(`/admin/users/${userId}/role`, { method: 'PATCH', body: { role: changes.role } })
    }
    if (changes.active !== undefined) {
      await call(`/admin/users/${userId}/status`, { method: 'PATCH', body: { is_active: changes.active } })
    }
  } catch (err) {
    if (err.status === 409) throw new Error('Sistemde en az bir aktif yönetici kalmalı.')
    throw err
  }
  return getUsers()
}

export const addUser = notAvailable('yöneticinin kullanıcı eklemesi (kullanıcılar kendileri kayıt olur)')

export function resetDemo() {}
export function setAnalysisUrl() {}
export function buildAnalysisRequest() {
  return null
}

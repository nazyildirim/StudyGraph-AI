// ------------------------------------------------------------
// ENTEGRASYON TESTİ: arayüz → Ranya'nın öğrenme analizi backend'i
// Önce backend'i başlat:  cd backend  →  uvicorn app.main:app --port 8000
// Sonra:                  npm.cmd run test:entegrasyon
// Backend çalışmıyorsa test atlanır.
// ------------------------------------------------------------
import { test } from 'node:test'
import * as api from './api.js'
import { initialExam, retestQuestions } from './mockData.js'

const URL = process.env.ANALYSIS_URL || 'http://127.0.0.1:8000/api/v1'

test('arayüz ile öğrenme analizi backend entegrasyonu', async (t) => {
  api.setAnalysisUrl(URL)
  if (!(await api.checkBackendHealth())) {
    t.skip(`Backend ${URL} adresinde çalışmıyor`)
    return
  }
  const fails = []
  const ok = (c, m) => (c ? console.log('ok  ', m) : fails.push(m))

  // Dokümandaki senaryoya yakın cevaplar: k1,k2 doğru; k3,k4,k5 yanlış
  const answers = {}
  for (const q of initialExam) answers[q.id] = ['k1', 'k2'].includes(q.outcomeId) ? q.answer : (q.answer + 1) % 4
  await api.submitInitialExam(1, answers)
  const req = api.buildAnalysisRequest(1)
  ok(req.question_results.length === 15 && req.prerequisite_edges.length === 6, 'istek sözleşme formatında (15 sonuç, 6 ön koşul)')

  let map = await api.getLearningMap(1)
  ok(map.analysisSource === 'backend', 'harita backend analiziyle geldi')
  ok(map.scores.k1 === 100 && map.scores.k3 === 0, 'puanlar backend hesabı: ' + JSON.stringify(map.scores))
  ok(map.statuses.k3.status === 'review' && map.statuses.k5.status === 'blocked', 'durumlar: k3 review, k5 blocked')
  let rec = await api.getRecommendation(1)
  ok(rec.outcome.id === 'k3', 'öneri: İç İçe Döngüler (backend)')

  // Kolay sınavda tam başarı → backend 100 der, sınır %69 uygulanır, k4 hâlâ blocked
  const easy = retestQuestions.k3.filter((q) => q.difficulty === 'easy')
  const ea = Object.fromEntries(easy.map((q) => [q.id, q.answer]))
  const r1 = await api.submitRetest(1, 'k3', ea, 'easy')
  map = await api.getLearningMap(1)
  ok(r1.capped && map.scores.k3 === 69, 'kolay sınav sınırı backend sonucuna uygulandı')
  ok(map.statuses.k4.status === 'blocked', 'k3 sınırlı olduğu için k4 blocked kaldı')

  // Orta zorlukta başarı → k3 completed, öneri Zaman Karmaşıklığı
  const med = retestQuestions.k3.filter((q) => q.difficulty === 'medium')
  await api.submitRetest(1, 'k3', Object.fromEntries(med.map((q) => [q.id, q.answer])), 'medium')
  rec = await api.getRecommendation(1)
  map = await api.getLearningMap(1)
  ok(map.statuses.k3.status === 'completed' && rec.outcome.id === 'k4', 'orta sınav sonrası k3 completed, öneri k4')
  ok(rec.blockedTopics.includes('Bubble Sort'), 'k4 öğrenilmeden Bubble Sort engelli')

  // Backend kapalıysa yerel hesaba düşer
  api.setAnalysisUrl('http://127.0.0.1:9/api/v1')
  map = await api.getLearningMap(1)
  rec = await api.getRecommendation(1)
  ok(map.analysisSource === 'local' && rec.outcome.id === 'k4', 'backend kapalı: yerel hesap aynı öneriyi verdi')
  if (fails.length) throw new Error('Başarısız: ' + fails.join(' | '))
})

// ------------------------------------------------------------
// ÖĞRENME MANTIĞI BİRİM TESTLERİ
// Çalıştırma: npm.cmd test  (ek kütüphane gerekmez, Node'un kendi test aracı)
// ------------------------------------------------------------
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  levelOf,
  scoreByOutcome,
  hasCycle,
  topologicalOrder,
  recommendNext,
  retestDecision,
  retestScore,
  pickQuestions,
} from './learningLogic.js'
import { outcomes, initialExam, retestQuestions } from './mockData.js'

test('puan seviyeye doğru çevrilir', () => {
  assert.equal(levelOf(70), 'sufficient')
  assert.equal(levelOf(69), 'developing')
  assert.equal(levelOf(40), 'developing')
  assert.equal(levelOf(39), 'missing')
  assert.equal(levelOf(undefined), 'unknown')
  assert.equal(levelOf(60, { sufficient: 60, developing: 30 }), 'sufficient')
})

test('aynı cevaplar her zaman aynı puanı verir (deterministik)', () => {
  const answers = { q1: 0, q2: 1, q3: 0, q4: 1 }
  const a = scoreByOutcome(initialExam, answers)
  const b = scoreByOutcome(initialExam, answers)
  assert.deepEqual(a, b)
  assert.equal(a.k1, 67) // 3 sorudan 2 doğru
  assert.equal(a.k3, 0)
})

test('örnek ön koşul grafiğinde döngü yok', () => {
  assert.equal(hasCycle(outcomes), false)
})

test('döngü oluşturan bağlantı tespit edilir', () => {
  const withCycle = outcomes.map((o) => (o.id === 'k1' ? { ...o, prerequisites: ['k5'] } : o))
  assert.equal(hasCycle(withCycle), true)
})

test('topolojik sırada her konu ön koşullarından sonra gelir', () => {
  const order = topologicalOrder(outcomes).map((o) => o.id)
  for (const o of outcomes) {
    for (const p of o.prerequisites) {
      assert.ok(order.indexOf(p) < order.indexOf(o.id), `${p} ${o.id}'den önce olmalı`)
    }
  }
})

test('dokümandaki senaryo: önce iç içe döngüler önerilir', () => {
  const scores = { k1: 90, k2: 80, k3: 30, k4: 20, k5: 25 }
  const rec = recommendNext(outcomes, scores)
  assert.equal(rec.outcome.id, 'k3')
})

test('ön koşulu eksik ileri konu önerilmez', () => {
  const scores = { k1: 90, k2: 80, k3: 30, k4: 20, k5: 25 }
  const rec = recommendNext(outcomes, scores)
  assert.notEqual(rec.outcome.id, 'k5') // Bubble Sort'un ön koşulları eksik
  assert.notEqual(rec.outcome.id, 'k4')
})

test('her şey yeterliyse öneri yok', () => {
  const scores = { k1: 100, k2: 100, k3: 100, k4: 100, k5: 100 }
  assert.equal(recommendNext(outcomes, scores), null)
})

test('tekrar sınavı karar kuralı', () => {
  assert.equal(retestDecision(0).type, 'alternative')
  assert.equal(retestDecision(2).type, 'alternative')
  assert.equal(retestDecision(3).type, 'practice')
  assert.equal(retestDecision(4).type, 'next')
  assert.equal(retestDecision(5).type, 'next')
})

test('kolay sınavda tam başarı konuyu "yeterli" yapmaz', () => {
  const r = retestScore(5, 5, 'easy')
  assert.equal(r.capped, true)
  assert.equal(r.score, 69)
  assert.equal(levelOf(r.score), 'developing')
})

test('orta ve zor sınavda puan sınırlanmaz', () => {
  assert.deepEqual(retestScore(4, 5, 'medium'), { score: 80, raw: 80, capped: false })
  assert.equal(retestScore(10, 10, 'hard').score, 100)
  assert.equal(retestScore(2, 5, 'easy').capped, false) // zaten yeterli değil
})

test('istenen zorlukta ve sayıda soru seçilir', () => {
  const pool = retestQuestions.k3
  const hard = pickQuestions(pool, 'hard', 3)
  assert.equal(hard.length, 3)
  assert.ok(hard.every((q) => q.difficulty === 'hard'))
  assert.equal(pickQuestions(pool, 'hard', 10).length, 3) // havuzda 3 zor soru var
  const mixed = pickQuestions(pool, 'mixed', 3)
  assert.deepEqual(mixed.map((q) => q.difficulty).sort(), ['easy', 'hard', 'medium'])
  assert.equal(new Set(pickQuestions(pool, 'mixed', 10).map((q) => q.id)).size, 10) // tekrar eden soru yok
})

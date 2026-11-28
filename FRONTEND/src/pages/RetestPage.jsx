// TEKRAR SINAVI EKRANI
// 1) Ayarlar: öğrenci zorluğu ve soru sayısını seçer
// 2) Sınav
// 3) Sonuç: puan değişimi ve karar
import { useEffect, useState } from 'react'
import { features, getRetest, getRetestOptions, submitRetest } from '../api/api.js'
import { difficultyLabels, questionCountOptions } from '../api/learningLogic.js'
import Quiz from '../components/Quiz.jsx'

const difficultyHints = {
  mixed: 'Kolay, orta ve zor sorular dengeli karışır. Önerilen seçenek.',
  easy: features.easyCap
    ? 'Konuya ısınmak için. Sadece kolay sorularla konu "Yeterli" sayılmaz.'
    : 'Konuya ısınmak için.',
  medium: 'Konuyu ne kadar anladığını ölçer.',
  hard: 'Kendini zorlamak için. Dikkatli düşünmen gereken sorular.',
}

export default function RetestPage({ course, outcome, go }) {
  const [options, setOptions] = useState(null) // her zorlukta kaç soru var
  const [settings, setSettings] = useState({ difficulty: 'mixed', count: 5 })
  const [questions, setQuestions] = useState(null)
  const [result, setResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (outcome) getRetestOptions(course.id, outcome.id).then(setOptions)
  }, [course.id, outcome])

  if (!outcome) {
    return (
      <div className="card empty">
        <p>Önce çalışacağın konuyu seç.</p>
        <button type="button" className="btn primary" onClick={() => go('study')}>
          Çalışma ekranına git
        </button>
      </div>
    )
  }

  async function start() {
    setLoading(true)
    setError('')
    try {
      setQuestions(await getRetest(course.id, outcome.id, settings))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(answers) {
    setSubmitting(true)
    setError('')
    try {
      setResult(await submitRetest(course.id, outcome.id, answers, settings.difficulty, questions.attemptId))
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  function restart() {
    setResult(null)
    setQuestions(null)
  }

  // ---------- 3) Sonuç ----------
  if (result) {
    return (
      <div className="narrow">
        <div className={`card result decision-${result.decision.type}`}>
          <span className="tag">
            {outcome.name} · Tekrar sınavı · {difficultyLabels[result.difficulty]}
          </span>
          <h1>
            {result.correct} / {result.total} doğru
          </h1>
          <p className="score-change">
            Kazanım puanı: <b>%{result.oldScore}</b> → <b>%{result.newScore}</b>
          </p>
          {result.capped && (
            <p className="note">
              Sınavda %{result.raw} başarı gösterdin. Kolay sorularla girilen sınav konuyu "Yeterli" yapamadığı için puanın
              %{result.newScore} olarak sayıldı. Konuyu tamamlamak için orta ya da karışık zorlukta dene.
            </p>
          )}
          <p>{result.decision.text}</p>
          <div className="row">
            <button type="button" className="btn primary" onClick={() => go('map')}>
              Güncellenmiş haritamı gör
            </button>
            <button type="button" className="btn" onClick={restart}>
              Farklı ayarlarla tekrar dene
            </button>
            {result.decision.type === 'alternative' && (
              <button type="button" className="btn" onClick={() => go('study')}>
                Konuyu tekrar çalış
              </button>
            )}
          </div>
          <p className="muted small">Not: Kısa bir sınav tek başına kesin yeterlik kanıtı değildir.</p>
        </div>
      </div>
    )
  }

  // ---------- 2) Sınav ----------
  if (questions) {
    return (
      <div className="narrow">
        <h1>{outcome.name} · Tekrar Sınavı</h1>
        <p className="muted">
          {difficultyLabels[settings.difficulty]} zorlukta {questions.length} soru. Sonuç haritana yansıyacak.
        </p>
        {questions.resumed && (
          <p className="note">
            {questions.differentSettings
              ? 'Daha önce başlattığın bir tekrar sınavı yarım kalmış. Yenisini açmadan önce onu bitirmen gerekiyor; kaldığın yerden devam ediyorsun.'
              : 'Yarım kalan tekrar sınavına kaldığın yerden devam ediyorsun.'}
          </p>
        )}
        {questions.unseen != null && questions.reused > 0 && (
          <p className="muted small">
            {questions.unseen} soru ilk kez karşına çıkıyor, {questions.reused} soru daha önce gördüğün sorulardan.
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <Quiz questions={questions} onSubmit={handleSubmit} submitting={submitting} />
      </div>
    )
  }

  // ---------- 1) Ayarlar ----------
  if (!options) return <p className="muted">Hazırlanıyor…</p>

  const known = options[settings.difficulty] !== null // canlı modda havuz büyüklüğü bilinmez
  const available = known ? options[settings.difficulty] : settings.count
  const willGet = Math.min(settings.count, available)

  return (
    <div className="narrow">
      <h1>{outcome.name} · Tekrar Sınavı</h1>
      <p className="muted">Sınavı kendine göre ayarla. Sonuç bu konunun puanını güncelleyecek.</p>

      <div className="card settings">
        <h3>Zorluk</h3>
        <div className="segmented four">
          {Object.entries(difficultyLabels).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={settings.difficulty === key ? 'active' : ''}
              disabled={options[key] === 0}
              onClick={() => setSettings({ ...settings, difficulty: key })}
            >
              {label}
              {options[key] !== null && <span className="count">havuzda {options[key]}</span>}
            </button>
          ))}
        </div>
        <p className="muted small">{difficultyHints[settings.difficulty]}</p>

        <h3>Soru sayısı</h3>
        <div className="segmented">
          {questionCountOptions.map((n) => (
            <button
              key={n}
              type="button"
              className={settings.count === n ? 'active' : ''}
              onClick={() => setSettings({ ...settings, count: n })}
            >
              {n} soru
            </button>
          ))}
        </div>
        {known && available < settings.count && (
          <p className="note">
            Bu zorlukta {available} soru var; sınav {willGet} soruyla yapılacak.
          </p>
        )}

        {error && <p className="error">{error}</p>}
        <div className="summary-line">
          <span>
            <b>{willGet}</b> soru · {difficultyLabels[settings.difficulty]} · yaklaşık {Math.max(1, Math.round(willGet * 0.75))} dk
          </span>
          <button type="button" className="btn primary" disabled={willGet === 0 || loading} onClick={start}>
            {loading ? 'Hazırlanıyor…' : 'Sınava başla'}
          </button>
        </div>
      </div>
    </div>
  )
}

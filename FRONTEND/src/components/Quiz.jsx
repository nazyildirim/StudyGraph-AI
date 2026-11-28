// ------------------------------------------------------------
// SINAV BİLEŞENİ
// Hem başlangıç sınavında (15 soru) hem tekrar sınavında (5 soru)
// aynı bileşen kullanılır. Soruları tek tek gösterir.
// ------------------------------------------------------------
import { useState } from 'react'

export default function Quiz({ questions, onSubmit, submitting }) {
  const [index, setIndex] = useState(0)
  const [answers, setAnswers] = useState({})

  const q = questions[index]
  const answeredCount = Object.keys(answers).length
  const allAnswered = answeredCount === questions.length

  function choose(optionIndex) {
    setAnswers({ ...answers, [q.id]: optionIndex })
  }

  return (
    <div className="quiz">
      <div className="progress">
        <div className="progress-bar" style={{ width: `${(answeredCount / questions.length) * 100}%` }} />
      </div>
      <p className="muted">
        Soru {index + 1} / {questions.length} · {answeredCount} cevaplandı
      </p>

      <div className="card question">
        <h3>{q.text}</h3>
        <div className="options">
          {q.options.map((opt, i) => (
            <button
              key={i}
              type="button"
              className={`option ${answers[q.id] === i ? 'chosen' : ''}`}
              onClick={() => choose(i)}
            >
              <span className="option-letter">{'ABCD'[i]}</span> {opt}
            </button>
          ))}
        </div>
      </div>

      <div className="quiz-nav">
        <button type="button" className="btn ghost" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          ← Önceki
        </button>
        {index < questions.length - 1 ? (
          <button type="button" className="btn" onClick={() => setIndex(index + 1)}>
            Sonraki →
          </button>
        ) : (
          <button
            type="button"
            className="btn primary"
            disabled={!allAnswered || submitting}
            onClick={() => onSubmit(answers)}
          >
            {submitting ? 'Gönderiliyor…' : allAnswered ? 'Sınavı bitir' : 'Tüm soruları cevapla'}
          </button>
        )}
      </div>

      <div className="dots">
        {questions.map((qq, i) => (
          <button
            key={qq.id}
            type="button"
            aria-label={`Soru ${i + 1}`}
            className={`qdot ${answers[qq.id] !== undefined ? 'done' : ''} ${i === index ? 'current' : ''}`}
            onClick={() => setIndex(i)}
          />
        ))}
      </div>
    </div>
  )
}

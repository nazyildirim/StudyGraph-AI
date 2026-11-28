// BAŞLANGIÇ SINAVI EKRANI (15 soru)
import { useEffect, useState } from 'react'
import { getInitialExam, submitInitialExam } from '../api/api.js'
import Quiz from '../components/Quiz.jsx'

export default function ExamPage({ course, onFinished, go }) {
  const [questions, setQuestions] = useState(null)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setError(null)
    getInitialExam(course.id)
      .then(setQuestions)
      .catch((err) => setError(err))
  }, [course.id])

  async function handleSubmit(answers) {
    setSubmitting(true)
    try {
      await submitInitialExam(course.id, answers, questions.attemptId)
      onFinished()
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  if (error) {
    return (
      <div className="card empty">
        <p>{error.message}</p>
        <button type="button" className="btn primary" onClick={() => go('map')}>
          Öğrenme haritama git
        </button>
      </div>
    )
  }

  if (!questions) return <p className="muted">Sınav hazırlanıyor…</p>

  return (
    <div className="narrow">
      <h1>{course.name} · Başlangıç Sınavı</h1>
      <p className="muted">
        {questions.length} soru. Her soru bir kazanımı ölçer. Sonuçlara göre kişisel öğrenme haritan oluşacak.
      </p>
      {questions.resumed && <p className="note">Yarım kalan sınavına kaldığın yerden devam ediyorsun.</p>}
      <Quiz questions={questions} onSubmit={handleSubmit} submitting={submitting} />
    </div>
  )
}

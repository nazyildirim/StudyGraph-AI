// BAŞLANGIÇ SINAVI EKRANI (15 soru)
import { useEffect, useState } from 'react'
import { getInitialExam, submitInitialExam } from '../api/api.js'
import Quiz from '../components/Quiz.jsx'

export default function ExamPage({ course, onFinished }) {
  const [questions, setQuestions] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    getInitialExam(course.id).then(setQuestions)
  }, [course.id])

  async function handleSubmit(answers) {
    setSubmitting(true)
    await submitInitialExam(course.id, answers)
    setSubmitting(false)
    onFinished()
  }

  if (!questions) return <p className="muted">Sınav hazırlanıyor…</p>

  return (
    <div className="narrow">
      <h1>{course.name} · Başlangıç Sınavı</h1>
      <p className="muted">
        {questions.length} soru. Her soru bir kazanımı ölçer. Sonuçlara göre kişisel öğrenme haritan oluşacak.
      </p>
      <Quiz questions={questions} onSubmit={handleSubmit} submitting={submitting} />
    </div>
  )
}

// SORU BANKASI: kazanıma bağlı çoktan seçmeli soru ekleme/silme
import { useEffect, useState } from 'react'
import { addQuestion, deleteQuestion, getOutcomes, getQuestions } from '../../api/api.js'
import { difficultyLabels } from '../../api/learningLogic.js'

const emptyForm = { outcomeId: '', kind: 'initial', difficulty: 'medium', text: '', options: ['', '', '', ''], answer: 0 }
const kindLabel = { initial: 'Başlangıç sınavı', retest: 'Tekrar sınavı' }

export default function QuestionManager({ course, onChanged }) {
  const [outcomes, setOutcomes] = useState(null)
  const [questions, setQuestions] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [filter, setFilter] = useState('')
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    getOutcomes(course.id).then(setOutcomes)
    getQuestions(course.id).then(setQuestions)
  }, [course.id])

  async function submit(e) {
    e.preventDefault()
    setMsg(null)
    try {
      setQuestions(await addQuestion(course.id, form))
      setForm({ ...emptyForm, outcomeId: form.outcomeId, kind: form.kind, difficulty: form.difficulty })
      setMsg({ ok: true, text: 'Soru eklendi.' })
      onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  async function remove(id) {
    setQuestions(await deleteQuestion(course.id, id))
    onChanged()
  }

  if (!outcomes) return <p className="muted">Yükleniyor…</p>
  if (outcomes.length === 0) {
    return (
      <div className="card empty">
        <p>Soru eklemeden önce bu derse en az bir kazanım tanımla (Kazanımlar sekmesi).</p>
      </div>
    )
  }

  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))
  const shown = questions.filter((q) => !filter || q.outcomeId === filter)
  const countFor = (id, kind) => questions.filter((q) => q.outcomeId === id && q.kind === kind).length

  return (
    <div className="two-col wide-right">
      <form className="card" onSubmit={submit}>
        <h3>Yeni soru ekle</h3>
        <label>
          Ölçtüğü kazanım
          <select value={form.outcomeId} onChange={(e) => setForm({ ...form, outcomeId: e.target.value })}>
            <option value="">Seç</option>
            {outcomes.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Hangi sınavda kullanılacak
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="initial">Başlangıç sınavı</option>
            <option value="retest">Tekrar sınavı</option>
          </select>
        </label>
        <label>
          Zorluk
          <select value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
            <option value="easy">Kolay</option>
            <option value="medium">Orta</option>
            <option value="hard">Zor</option>
          </select>
        </label>
        <label>
          Soru metni
          <textarea rows={3} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
        </label>
        <span className="muted small">Seçenekler (doğru olanı işaretle):</span>
        {form.options.map((opt, i) => (
          <div key={i} className="option-input">
            <input
              type="radio"
              name="answer"
              checked={form.answer === i}
              onChange={() => setForm({ ...form, answer: i })}
              aria-label={`${'ABCD'[i]} doğru cevap`}
            />
            <span className="option-letter">{'ABCD'[i]}</span>
            <input
              value={opt}
              onChange={(e) => {
                const options = [...form.options]
                options[i] = e.target.value
                setForm({ ...form, options })
              }}
            />
          </div>
        ))}
        {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}
        <button type="submit" className="btn primary">
          Soruyu ekle
        </button>
      </form>

      <div className="card">
        <div className="panel-head">
          <h3>Soru bankası ({questions.length})</h3>
          <select className="auto" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">Tüm kazanımlar</option>
            {outcomes.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} ({countFor(o.id, 'initial')} + {countFor(o.id, 'retest')})
              </option>
            ))}
          </select>
        </div>
        <p className="muted small">Parantezde: başlangıç sınavı + tekrar sınavı soru sayısı.</p>
        {shown.length === 0 && <p className="muted">Bu filtrede soru yok.</p>}
        <ul className="list">
          {shown.map((q) => (
            <li key={q.id}>
              <div>
                <span className="tag">{kindLabel[q.kind]}</span>{' '}
                <span className={`tag diff-${q.difficulty || 'medium'}`}>{difficultyLabels[q.difficulty || 'medium']}</span>{' '}
                <span className="tag accent">{byId[q.outcomeId]?.name}</span>
                <div>{q.text}</div>
                <div className="muted small">Doğru: {'ABCD'[q.answer]}) {q.options[q.answer]}</div>
              </div>
              <button type="button" className="btn small ghost danger" onClick={() => remove(q.id)}>
                Sil
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

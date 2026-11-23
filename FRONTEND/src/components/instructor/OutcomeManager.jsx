// KAZANIM YÖNETİMİ: kazanım ekleme/silme ve ön koşul bağlantıları
import { useEffect, useState } from 'react'
import { addOutcome, addPrerequisite, deleteOutcome, getOutcomes } from '../../api/api.js'
import LearningGraph from '../LearningGraph.jsx'
import { defaultThresholds } from '../../api/learningLogic.js'

export default function OutcomeManager({ course, onChanged }) {
  const [outcomes, setOutcomes] = useState(null)
  const [name, setName] = useState('')
  const [prereqs, setPrereqs] = useState([])
  const [link, setLink] = useState({ outcomeId: '', prerequisiteId: '' })
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    getOutcomes(course.id).then(setOutcomes)
  }, [course.id])

  async function run(fn, okText) {
    setMsg(null)
    try {
      const updated = await fn()
      setOutcomes(updated)
      setMsg({ ok: true, text: okText })
      onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    }
  }

  if (!outcomes) return <p className="muted">Yükleniyor…</p>
  const byId = Object.fromEntries(outcomes.map((o) => [o.id, o]))

  return (
    <div>
      <div className="two-col">
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault()
            run(() => addOutcome(course.id, name, prereqs), `"${name}" kazanımı eklendi.`).then(() => {
              setName('')
              setPrereqs([])
            })
          }}
        >
          <h3>Yeni kazanım ekle</h3>
          <label>
            Kazanım adı
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Örn. Süreç zamanlama" />
          </label>
          {outcomes.length > 0 && (
            <div className="checks">
              <span className="muted small">Ön koşulları (önce bilinmesi gerekenler):</span>
              {outcomes.map((o) => (
                <label key={o.id} className="check">
                  <input
                    type="checkbox"
                    checked={prereqs.includes(o.id)}
                    onChange={(e) =>
                      setPrereqs(e.target.checked ? [...prereqs, o.id] : prereqs.filter((p) => p !== o.id))
                    }
                  />
                  {o.name}
                </label>
              ))}
            </div>
          )}
          <button type="submit" className="btn primary">
            Kazanımı ekle
          </button>
        </form>

        <div className="card">
          <h3>Kazanımlar ({outcomes.length})</h3>
          {outcomes.length === 0 && <p className="muted">Henüz kazanım yok.</p>}
          <ul className="list">
            {outcomes.map((o) => (
              <li key={o.id}>
                <div>
                  <b>{o.name}</b>
                  <div className="muted small">
                    Ön koşul: {o.prerequisites.length ? o.prerequisites.map((p) => byId[p]?.name).join(', ') : 'yok'}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn small ghost danger"
                  onClick={() => {
                    if (window.confirm(`"${o.name}" ve bu kazanıma bağlı sorular silinsin mi?`)) {
                      run(() => deleteOutcome(course.id, o.id), 'Kazanım silindi.')
                    }
                  }}
                >
                  Sil
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {msg && <p className={msg.ok ? 'success' : 'error'}>{msg.text}</p>}

      {outcomes.length > 0 && (
        <div className="card">
          <h3>Ön koşul grafiği</h3>
          <LearningGraph outcomes={outcomes} scores={{}} thresholds={defaultThresholds} />
          {outcomes.length > 1 && (
            <form
              className="link-form"
              onSubmit={(e) => {
                e.preventDefault()
                run(() => addPrerequisite(course.id, link.outcomeId, link.prerequisiteId), 'Ön koşul bağlantısı eklendi.')
              }}
            >
              <b>Yeni bağlantı:</b>
              <select value={link.prerequisiteId} onChange={(e) => setLink({ ...link, prerequisiteId: e.target.value })}>
                <option value="">Önce öğrenilecek konu</option>
                {outcomes.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
              <span>→</span>
              <select value={link.outcomeId} onChange={(e) => setLink({ ...link, outcomeId: e.target.value })}>
                <option value="">Sonraki konu</option>
                {outcomes.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
              <button type="submit" className="btn" disabled={!link.outcomeId || !link.prerequisiteId}>
                Ekle
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  )
}

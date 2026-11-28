// ÇALIŞMA EKRANI: yapay zekâ asistanı (kaynak gösterimli) + tekrar sınavına geçiş
import { useEffect, useRef, useState } from 'react'
import { askAssistant, features, getOutcomes, getRecommendation } from '../api/api.js'

export default function StudyPage({ course, outcome, setOutcome, go }) {
  const [outcomes, setOutcomes] = useState([])
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('topic_explanation') // canlı modda cevap türü
  const endRef = useRef(null)

  // Konu seçilmediyse önerilen konuyu kullan
  useEffect(() => {
    getOutcomes(course.id).then(setOutcomes).catch(() => setOutcomes([]))
    if (!outcome) {
      getRecommendation(course.id)
        .then((r) => r && setOutcome(r.outcome))
        .catch(() => {})
    }
  }, [course.id, outcome, setOutcome])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const suggestions = outcome
    ? [
        `${outcome.name} konusunu tabloyla açıkla`,
        `${outcome.name} için bir Python örneği ver`,
        `${outcome.name} hakkında bana iki soru sor`,
      ]
    : []

  async function send(text) {
    const question = (text ?? input).trim()
    if (!question) return
    setInput('')
    setMessages((m) => [...m, { from: 'user', text: question }])
    setLoading(true)
    try {
      const res = await askAssistant(course.id, question, outcome?.id, mode)
      setMessages((m) => [
        ...m,
        { from: 'ai', text: res.answer, sources: res.sources, grounded: res.grounded, fallback: res.fallback },
      ])
    } catch (err) {
      setMessages((m) => [...m, { from: 'ai', text: 'Bir hata oluştu: ' + err.message, sources: [] }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="study">
      <div className="study-head">
        <div>
          <h1>Çalış & Asistan</h1>
          <label className="inline">
            Konu:
            <select
              value={outcome?.id || ''}
              onChange={(e) => {
                setOutcome(outcomes.find((o) => o.id === e.target.value))
                setMessages([])
              }}
            >
              <option value="" disabled>
                Konu seç
              </option>
              {outcomes.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button type="button" className="btn primary" disabled={!outcome} onClick={() => go('retest')}>
          Tekrar sınavına geç →
        </button>
      </div>

      {features.assistantModes && (
        <div className="segmented modes" role="group" aria-label="Cevap türü">
          {[
            ['topic_explanation', 'Konu anlatımı'],
            ['code_example', 'Kod örneği'],
            ['exercise', 'Alıştırma'],
          ].map(([key, label]) => (
            <button key={key} type="button" className={mode === key ? 'active' : ''} onClick={() => setMode(key)}>
              {label}
            </button>
          ))}
        </div>
      )}

      <div className="card chat">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty-chat">
              <p className="muted">Ders notlarına dayanarak sorularını cevaplarım. Kullandığım kaynakları da gösteririm.</p>
              <div className="chips">
                {suggestions.map((s) => (
                  <button key={s} type="button" className="chip" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.from}`}>
              <div className="bubble">
                {m.grounded === false && (
                  <div className="note small">Ders notlarında bu soruyla ilgili kaynak bulunamadı; cevap kaynaksız.</div>
                )}
                {m.fallback && (
                  <div className="note small">Yapay zekâ modeli şu an kapalı; cevap ders notlarından doğrudan alındı.</div>
                )}
                {m.text}
                {m.sources && m.sources.length > 0 && (
                  <div className="sources">
                    <b>Kaynaklar:</b>
                    {m.sources.map((s, j) => (
                      <span key={j} className="source">
                        {s.id ? `[${s.id}] ` : ''}
                        {s.title}
                        {s.page ? ` · s. ${s.page}` : ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="msg ai">
              <div className="bubble muted">
                Ders notları taranıyor…
                {features.assistantModes && <div className="small">Yapay zekâ ilk soruda 30 saniye kadar sürebilir.</div>}
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        <form
          className="chat-input"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Sorunu yaz…" />
          <button type="submit" className="btn primary" disabled={loading}>
            Gönder
          </button>
        </form>
      </div>
    </div>
  )
}

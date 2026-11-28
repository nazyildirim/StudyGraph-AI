// ÖĞRENME HARİTASI EKRANI: renkli grafik + öneri + ilerleme geçmişi
import { useEffect, useState } from 'react'
import { getLearningMap, getRecommendation } from '../api/api.js'
import { levelOf, levelLabels, difficultyLabels } from '../api/learningLogic.js'
import LearningGraph from '../components/LearningGraph.jsx'

export default function MapPage({ course, go, onStudy }) {
  const [map, setMap] = useState(null)
  const [rec, setRec] = useState(undefined)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setError('')
    Promise.all([getLearningMap(course.id), getRecommendation(course.id)])
      .then(([m, r]) => {
        setMap(m)
        setRec(r)
      })
      .catch((err) => setError(err.message))
  }, [course.id])

  if (error) {
    return (
      <div className="card empty">
        <p>{error}</p>
      </div>
    )
  }

  if (!map || rec === undefined) return <p className="muted">Harita yükleniyor…</p>

  if (Object.keys(map.scores).length === 0) {
    return (
      <div className="card empty">
        <h2>Henüz haritan yok</h2>
        <p className="muted">Haritanın oluşması için önce başlangıç sınavını çöz.</p>
        <button type="button" className="btn primary" onClick={() => go('exam')}>
          Başlangıç sınavına git
        </button>
      </div>
    )
  }

  const byId = Object.fromEntries(map.outcomes.map((o) => [o.id, o]))

  return (
    <div>
      <div className="panel-head">
        <h1>{course.name} · Öğrenme Haritam</h1>
        <span
          className={`tag source ${map.analysisSource === 'backend' ? 'live' : ''}`}
          title={
            map.analysisSource === 'backend'
              ? 'Puanlar ve öneriler StudyGraph öğrenme analizi servisinden geliyor.'
              : 'Backend kapalı; puanlar ve öneriler tarayıcıda hesaplandı.'
          }
        >
          {map.analysisSource === 'backend' ? 'Analiz: backend' : 'Analiz: yerel (backend kapalı)'}
        </span>
      </div>

      {rec ? (
        <div className="card recommendation">
          <div>
            <span className="tag accent">Sıradaki önerilen konu</span>
            <h2>{rec.outcome.name}</h2>
            <p className="muted">
              {rec.outcome.prerequisites.length ? 'Bu konunun tüm ön koşulları yeterli seviyede.' : 'Bu konunun ön koşulu yok.'}
              {rec.blockedTopics.length > 0 &&
                ` Bu konuyu öğrenmeden ${rec.blockedTopics.join(', ')} ${rec.blockedTopics.length > 1 ? 'konularına' : 'konusuna'} geçmen önerilmez.`}
            </p>
          </div>
          <button type="button" className="btn primary" onClick={() => onStudy(rec.outcome)}>
            Bu konuyu çalış →
          </button>
        </div>
      ) : (
        <div className="card recommendation done">
          <h2>Tebrikler!</h2>
          <p className="muted">Bu dersteki tüm kazanımlarda yeterli seviyedesin.</p>
        </div>
      )}

      <div className="card">
        <h3>Ön koşul grafiği</h3>
        <p className="muted small">Oklar "önce bunu öğren" anlamına gelir. Ayrıntı için bir konuya tıkla.</p>
        <LearningGraph
          outcomes={map.outcomes}
          scores={map.scores}
          thresholds={map.thresholds}
          recommendedId={rec?.outcome.id}
          selectedId={selected?.id}
          onSelect={setSelected}
        />
      </div>

      {selected && (
        <div className="card">
          <h3>{selected.name}</h3>
          <p>
            Puan: <b>%{map.scores[selected.id] ?? '-'}</b> ·{' '}
            {levelLabels[levelOf(map.scores[selected.id], map.thresholds)]}
          </p>
          <p className="muted">
            Ön koşulları:{' '}
            {selected.prerequisites.length ? selected.prerequisites.map((p) => byId[p].name).join(', ') : 'yok'}
          </p>
          <button type="button" className="btn" onClick={() => onStudy(selected)}>
            Bu konuyu çalış
          </button>
        </div>
      )}

      <div className="card">
        <h3>İlerlemem</h3>
        <p className="muted small">Açık çubuk ilk sınavdaki puan, koyu çubuk şu anki puan.</p>
        {map.outcomes.map((o) => {
          const first = map.history[0]?.scores[o.id] ?? 0
          const now = map.scores[o.id] ?? 0
          const diff = now - first
          return (
            <div key={o.id} className="progress-row">
              <span className="bar-label">{o.name}</span>
              <div className="bar double">
                <div className="bar-first" style={{ width: `${first}%` }} />
                <div className={`bar-now level-${levelOf(now, map.thresholds)}`} style={{ width: `${now}%` }} />
              </div>
              <span className={`bar-value ${diff > 0 ? 'success' : ''}`}>
                %{now} {diff > 0 ? `(+${diff})` : ''}
              </span>
            </div>
          )
        })}
      </div>

      <div className="card">
        <h3>Ölçüm geçmişi</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Tarih</th>
              <th>Değerlendirme</th>
              {map.outcomes.map((o) => (
                <th key={o.id}>{o.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {map.history.map((h, i) => (
              <tr key={i}>
                <td>{new Date(h.date).toLocaleString('tr-TR', { dateStyle: 'short', timeStyle: 'short' })}</td>
                <td>
                  {h.type}
                  {h.outcomeId ? ` (${byId[h.outcomeId]?.name})` : ''}
                  {h.difficulty && (
                    <span className="muted small">
                      {' '}
                      · {difficultyLabels[h.difficulty]}, {h.questionCount} soru
                    </span>
                  )}
                </td>
                {map.outcomes.map((o) => (
                  <td key={o.id} className={`cell level-${levelOf(h.scores[o.id], map.thresholds)}`}>
                    {h.scores[o.id] !== undefined ? `%${h.scores[o.id]}` : '-'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

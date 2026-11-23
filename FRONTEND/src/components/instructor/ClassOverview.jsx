// GENEL BAKIŞ: sınıf raporu ve başarı eşikleri
import { useEffect, useState } from 'react'
import { getClassReport, getLearningMap, resetDemo, updateThresholds } from '../../api/api.js'
import { levelOf } from '../../api/learningLogic.js'

export default function ClassOverview({ course, go }) {
  const [map, setMap] = useState(null)
  const [report, setReport] = useState(null)
  const [thresholds, setThresholds] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getLearningMap(course.id).then((m) => {
      setMap(m)
      setThresholds(m.thresholds)
    })
    getClassReport(course.id).then(setReport)
  }, [course.id])

  if (!map || !report || !thresholds) return <p className="muted">Yükleniyor…</p>

  const byId = Object.fromEntries(map.outcomes.map((o) => [o.id, o]))
  const ranking = Object.entries(report.strugglingByOutcome)
    .filter(([id]) => byId[id])
    .sort((a, b) => b[1] - a[1])
  const top = ranking[0]

  async function saveThresholds() {
    await updateThresholds(course.id, thresholds)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div>
      {!course.active && (
        <div className="card highlight">
          <h3>Bu ders henüz öğrencilere açık değil</h3>
          <p className="muted">
            Açılması için en az bir kazanım ve bir başlangıç sınavı sorusu gerekiyor. Şu an: {course.outcomeCount} kazanım,{' '}
            {course.questionCount} soru.
          </p>
          <div className="row">
            <button type="button" className="btn primary" onClick={() => go('outcomes')}>
              Kazanım ekle
            </button>
            <button type="button" className="btn" onClick={() => go('questions')}>
              Soru ekle
            </button>
          </div>
        </div>
      )}

      {top && (
        <div className="card highlight">
          <h3>Sınıf özeti</h3>
          <p>
            {report.studentCount} öğrenciden <b>{top[1]}</b> tanesi <b>{byId[top[0]].name}</b> konusunda zorlanıyor. Bu konu
            için ek öğretim etkinliği planlanabilir.
          </p>
        </div>
      )}

      <div className="two-col">
        <div className="card">
          <h3>En çok zorlanılan konular</h3>
          {ranking.length === 0 && <p className="muted">Bu ders için henüz öğrenci sonucu yok.</p>}
          {ranking.map(([id, count]) => {
            const pct = Math.round((count / report.studentCount) * 100)
            return (
              <div key={id} className="bar-row">
                <span className="bar-label">{byId[id].name}</span>
                <div className="bar">
                  <div className="bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="bar-value">
                  {count}/{report.studentCount}
                </span>
              </div>
            )
          })}
        </div>

        <div className="card">
          <h3>Başarı eşikleri</h3>
          <label>
            Yeterli sayılma eşiği: %{thresholds.sufficient}
            <input
              type="range"
              min="50"
              max="100"
              value={thresholds.sufficient}
              onChange={(e) => setThresholds({ ...thresholds, sufficient: Number(e.target.value) })}
            />
          </label>
          <label>
            Geliştirilmeli eşiği: %{thresholds.developing}
            <input
              type="range"
              min="10"
              max={thresholds.sufficient - 5}
              value={thresholds.developing}
              onChange={(e) => setThresholds({ ...thresholds, developing: Number(e.target.value) })}
            />
          </label>
          <button type="button" className="btn primary" onClick={saveThresholds}>
            {saved ? 'Kaydedildi ✓' : 'Eşikleri kaydet'}
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Bireysel öğrenci ilerlemesi</h3>
        {report.students.length === 0 ? (
          <p className="muted">Bu ders için henüz öğrenci sonucu yok.</p>
        ) : (
          <>
            <p className="muted small">Her hücrede: ilk sınav → son durum.</p>
            <table className="table">
              <thead>
                <tr>
                  <th>Öğrenci</th>
                  {map.outcomes.map((o) => (
                    <th key={o.id}>{o.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.students.map((st) => (
                  <tr key={st.name}>
                    <td>{st.name}</td>
                    {map.outcomes.map((o) => {
                      const a = st.first[o.id]
                      const b = st.last[o.id]
                      return (
                        <td key={o.id} className={`cell level-${levelOf(b, thresholds)}`}>
                          {a === undefined ? '-' : `%${a} → %${b}`}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="card">
        <h3>Demo verisi</h3>
        <p className="muted small">Sunumdan önce eklenen dersleri, soruları ve tüm sonuçları ilk hâline döndürür.</p>
        <button
          type="button"
          className="btn ghost danger"
          onClick={() => {
            if (window.confirm('Tüm demo verisi ilk hâline dönsün mü?')) {
              resetDemo()
              window.location.reload()
            }
          }}
        >
          Demo verisini sıfırla
        </button>
      </div>
    </div>
  )
}

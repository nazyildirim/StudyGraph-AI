// ------------------------------------------------------------
// AKADEMİSYEN PANELİ
// Sekmeler: Genel Bakış · Dersler · Kazanımlar · Soru Bankası · Ders Notları
// Üstteki seçiciden hangi ders üzerinde çalışılacağı seçilir.
// ------------------------------------------------------------
import { useCallback, useEffect, useState } from 'react'
import { getCourses } from '../api/api.js'
import ClassOverview from '../components/instructor/ClassOverview.jsx'
import CourseManager from '../components/instructor/CourseManager.jsx'
import OutcomeManager from '../components/instructor/OutcomeManager.jsx'
import QuestionManager from '../components/instructor/QuestionManager.jsx'
import MaterialManager from '../components/instructor/MaterialManager.jsx'

const TABS = [
  { id: 'overview', label: 'Genel Bakış' },
  { id: 'courses', label: 'Dersler' },
  { id: 'outcomes', label: 'Kazanımlar' },
  { id: 'questions', label: 'Soru Bankası' },
  { id: 'materials', label: 'Ders Notları' },
]

export default function InstructorPage() {
  const [courses, setCourses] = useState(null)
  const [courseId, setCourseId] = useState(null)
  const [tab, setTab] = useState('overview')

  // Ders listesini yeniden yükler (bir şey eklenince/silinince çağrılır)
  const reload = useCallback(async () => {
    const cs = await getCourses()
    setCourses(cs)
    setCourseId((cur) => (cs.some((c) => c.id === cur) ? cur : cs[0]?.id ?? null))
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  if (!courses) return <p className="muted">Panel yükleniyor…</p>

  const course = courses.find((c) => c.id === courseId)

  return (
    <div>
      <div className="panel-head">
        <h1>Akademisyen Paneli</h1>
        {courses.length > 0 && (
          <label className="inline">
            Ders:
            <select value={courseId ?? ''} onChange={(e) => setCourseId(Number(e.target.value))}>
              {courses.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} type="button" className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'courses' && (
        <CourseManager
          courses={courses}
          onChanged={reload}
          onOpen={(id, next) => {
            setCourseId(id)
            setTab(next)
          }}
        />
      )}

      {tab !== 'courses' && !course && (
        <div className="card empty">
          <p>Henüz ders yok. Önce "Dersler" sekmesinden bir ders ekle.</p>
          <button type="button" className="btn primary" onClick={() => setTab('courses')}>
            Ders ekle
          </button>
        </div>
      )}

      {course && tab === 'overview' && <ClassOverview key={course.id} course={course} go={setTab} />}
      {course && tab === 'outcomes' && <OutcomeManager key={course.id} course={course} onChanged={reload} />}
      {course && tab === 'questions' && <QuestionManager key={course.id} course={course} onChanged={reload} />}
      {course && tab === 'materials' && <MaterialManager key={course.id} course={course} onChanged={reload} />}
    </div>
  )
}

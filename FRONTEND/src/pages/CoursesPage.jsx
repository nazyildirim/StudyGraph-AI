// DERS SEÇİMİ EKRANI
import { useEffect, useState } from 'react'
import { getCourses } from '../api/api.js'

export default function CoursesPage({ onSelectCourse }) {
  const [courses, setCourses] = useState(null)

  useEffect(() => {
    getCourses().then(setCourses)
  }, [])

  if (!courses) return <p className="muted">Dersler yükleniyor…</p>

  return (
    <div>
      <h1>Derslerim</h1>
      <p className="muted">Başlamak için bir ders seç. İlk adım kısa bir başlangıç sınavı.</p>
      <div className="grid">
        {courses.map((c) => (
          <div key={c.id} className={`card course ${c.active ? '' : 'disabled'}`}>
            <span className="tag">{c.code}</span>
            <h2>{c.name}</h2>
            <p className="muted">{c.description}</p>
            <button
              type="button"
              className="btn primary"
              disabled={!c.active}
              onClick={() => onSelectCourse(c)}
            >
              {c.active ? 'Derse başla' : 'Hazırlanıyor'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

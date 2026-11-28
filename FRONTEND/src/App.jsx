// ------------------------------------------------------------
// ANA UYGULAMA
// Hangi ekranın gösterileceğine burası karar verir.
// Akış: Giriş → Dersler → Başlangıç sınavı → Harita → Çalış → Tekrar sınavı → Harita
// ------------------------------------------------------------
import { useEffect, useState } from 'react'
import './App.css'
import { logout, getCourses } from './api/api.js'
import Header from './components/Header.jsx'
import LoginPage from './pages/LoginPage.jsx'
import CoursesPage from './pages/CoursesPage.jsx'
import ExamPage from './pages/ExamPage.jsx'
import MapPage from './pages/MapPage.jsx'
import StudyPage from './pages/StudyPage.jsx'
import RetestPage from './pages/RetestPage.jsx'
import InstructorPage from './pages/InstructorPage.jsx'
import AdminPage from './pages/AdminPage.jsx'

const DEFAULT_COURSE = { id: 1, code: 'BİM201', name: 'Algoritma Analizi' }

export default function App() {
  const [user, setUser] = useState(null) // giriş yapan kullanıcı
  const [page, setPage] = useState('login') // gösterilen ekran
  const [course, setCourse] = useState(DEFAULT_COURSE) // seçili ders
  const [outcome, setOutcome] = useState(null) // çalışılan konu
  const [notice, setNotice] = useState('') // giriş ekranında gösterilecek mesaj

  // Canlı modda ilk dersi varsayılan yap
  useEffect(() => {
    getCourses().then((cs) => cs[0] && setCourse((c) => (cs.some((x) => x.id === c.id) ? c : cs[0])))
  }, [])

  // Canlı modda token süresi dolarsa (401) girişe dön
  useEffect(() => {
    const onExpired = () => {
      setUser(null)
      setOutcome(null)
      setPage('login')
      setNotice('Oturumun sona erdi, lütfen tekrar giriş yap.')
    }
    window.addEventListener('studygraph:unauthorized', onExpired)
    return () => window.removeEventListener('studygraph:unauthorized', onExpired)
  }, [])

  function go(next) {
    setPage(next)
    window.scrollTo(0, 0)
  }

  if (!user) {
    return (
      <LoginPage
        notice={notice}
        onLogin={(u) => {
          setNotice('')
          setUser(u)
          go({ instructor: 'instructor', admin: 'admin' }[u.role] || 'courses')
        }}
      />
    )
  }

  let content
  switch (page) {
    case 'courses':
      content = (
        <CoursesPage
          onSelectCourse={(c) => {
            setCourse(c)
            go('exam')
          }}
        />
      )
      break
    case 'exam':
      content = <ExamPage course={course} onFinished={() => go('map')} go={go} />
      break
    case 'map':
      content = (
        <MapPage
          course={course}
          go={go}
          onStudy={(o) => {
            setOutcome(o)
            go('study')
          }}
        />
      )
      break
    case 'study':
      content = <StudyPage course={course} outcome={outcome} setOutcome={setOutcome} go={go} />
      break
    case 'retest':
      content = <RetestPage course={course} outcome={outcome} go={go} />
      break
    case 'instructor':
      content = <InstructorPage />
      break
    case 'admin':
      content = <AdminPage currentUser={user} />
      break
    default:
      content = <p>Sayfa bulunamadı.</p>
  }

  return (
    <div className="app">
      <Header
        user={user}
        page={page}
        go={go}
        onLogout={() => {
          logout()
          setUser(null)
          setOutcome(null)
          go('login')
        }}
      />
      <main className="container">{content}</main>
    </div>
  )
}

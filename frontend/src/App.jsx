// 应用顶层：切换学生端 / 心理老师端。

import { useState } from 'react'
import StudentPage from './pages/StudentPage'
import TeacherPage from './pages/TeacherPage'

export default function App() {
  const [view, setView] = useState('student')

  return (
    <>
      <nav className="app-switcher">
        <button className={view === 'student' ? 'active' : 'ghost'}
          onClick={() => setView('student')}>学生端</button>
        <button className={view === 'teacher' ? 'active' : 'ghost'}
          onClick={() => setView('teacher')}>心理老师端</button>
      </nav>
      {view === 'student' ? <StudentPage /> : <TeacherPage />}
    </>
  )
}

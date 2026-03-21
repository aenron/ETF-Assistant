import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import { DashboardPage } from '@/pages/DashboardPage'
import { PortfolioPage } from '@/pages/PortfolioPage'
import { AdvicePage } from '@/pages/AdvicePage'
import LoginPage from '@/pages/LoginPage'
import { LayoutDashboard, Briefcase, Lightbulb, LogOut, User } from 'lucide-react'
import { isAuthenticated, getCurrentUser, removeToken } from '@/services/authApi'
import { useState, useEffect } from 'react'
import { LLMSelector } from '@/components/LLMSelector'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/login" replace />
}

function AppContent() {
  const location = useLocation()
  const [user, setUser] = useState(getCurrentUser())
  const [authed, setAuthed] = useState(isAuthenticated())

  useEffect(() => {
    setAuthed(isAuthenticated())
    setUser(getCurrentUser())
  }, [location])

  const handleLogout = () => {
    removeToken()
    window.location.href = '/login'
  }

  return (
    <div className="min-h-screen bg-background">
      {authed && (
          <header className="border-b">
            <div className="container mx-auto px-4 h-14 flex items-center justify-between">
              <h1 className="text-xl font-bold">ETF投资智能体</h1>
              <nav className="flex items-center gap-6">
                <NavLink
                  to="/"
                  className={({ isActive }) =>
                    `flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary ${
                      isActive ? 'text-primary' : 'text-muted-foreground'
                    }`
                  }
                >
                  <LayoutDashboard className="h-4 w-4" />
                  仪表盘
                </NavLink>
                <NavLink
                  to="/portfolio"
                  className={({ isActive }) =>
                    `flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary ${
                      isActive ? 'text-primary' : 'text-muted-foreground'
                    }`
                  }
                >
                  <Briefcase className="h-4 w-4" />
                  持仓管理
                </NavLink>
                <NavLink
                  to="/advice"
                  className={({ isActive }) =>
                    `flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary ${
                      isActive ? 'text-primary' : 'text-muted-foreground'
                    }`
                  }
                >
                  <Lightbulb className="h-4 w-4" />
                  决策历史
                </NavLink>
              </nav>
              <div className="flex items-center gap-4">
                <LLMSelector />
                <span className="flex items-center gap-1 text-sm text-muted-foreground">
                  <User className="h-4 w-4" />
                  {user?.username}
                </span>
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
                >
                  <LogOut className="h-4 w-4" />
                  退出
                </button>
              </div>
            </div>
          </header>
        )}
      <main className="container mx-auto px-4 py-6">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
          <Route path="/portfolio" element={<PrivateRoute><PortfolioPage /></PrivateRoute>} />
          <Route path="/advice" element={<PrivateRoute><AdvicePage /></PrivateRoute>} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  )
}

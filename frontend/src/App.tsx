import { Suspense, lazy, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom'
import { LayoutDashboard, Briefcase, Lightbulb, LogOut, User } from 'lucide-react'
import { isAuthenticated, getCurrentUser, removeToken } from '@/services/authApi'
import { LLMSelector } from '@/components/LLMSelector'
import { FloatingAssistant } from '@/components/FloatingAssistant'

const DashboardPage = lazy(() =>
  import('@/pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
)
const PortfolioPage = lazy(() =>
  import('@/pages/PortfolioPage').then((module) => ({ default: module.PortfolioPage })),
)
const AdvicePage = lazy(() =>
  import('@/pages/AdvicePage').then((module) => ({ default: module.AdvicePage })),
)
const LoginPage = lazy(() => import('@/pages/LoginPage'))

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/login" replace />
}

function AppContent() {
  const location = useLocation()
  const [user, setUser] = useState(getCurrentUser())
  const [authed, setAuthed] = useState(isAuthenticated())
  const navItems = [
    { to: '/', label: '仪表盘', icon: LayoutDashboard },
    { to: '/portfolio', label: '持仓管理', icon: Briefcase },
    { to: '/advice', label: '决策历史', icon: Lightbulb },
  ]

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
        <header className="border-b bg-background/95 backdrop-blur">
          <div className="container mx-auto px-3 py-3 sm:px-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center justify-between gap-3">
                <h1 className="text-lg font-bold sm:text-xl">ETF投资智能体</h1>
                <div className="flex items-center gap-2 lg:hidden">
                  <LLMSelector />
                </div>
              </div>

              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-6">
                <nav className="flex gap-2 overflow-x-auto pb-1 lg:overflow-visible lg:pb-0">
                  {navItems.map((item) => {
                    const Icon = item.icon
                    return (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className={({ isActive }) =>
                          `flex shrink-0 items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium transition-colors ${
                            isActive
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'border-transparent bg-muted/40 text-muted-foreground hover:text-primary'
                          }`
                        }
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </NavLink>
                    )
                  })}
                </nav>

                <div className="flex items-center justify-between gap-3 lg:justify-end">
                  <div className="hidden lg:block">
                    <LLMSelector />
                  </div>
                  <span className="flex items-center gap-1 text-sm text-muted-foreground">
                    <User className="h-4 w-4" />
                    <span className="max-w-28 truncate sm:max-w-none">{user?.username}</span>
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
            </div>
          </div>
        </header>
      )}
      <main className="container mx-auto px-3 py-4 sm:px-4 sm:py-6">
        <Suspense fallback={<div className="py-12 text-center text-sm text-muted-foreground">页面加载中...</div>}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
            <Route path="/portfolio" element={<PrivateRoute><PortfolioPage /></PrivateRoute>} />
            <Route path="/advice" element={<PrivateRoute><AdvicePage /></PrivateRoute>} />
          </Routes>
        </Suspense>
      </main>
      {authed && <div className="pb-20 md:pb-0"><FloatingAssistant /></div>}
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

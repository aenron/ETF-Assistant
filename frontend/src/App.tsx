import { Suspense, lazy, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Briefcase, Lightbulb, LogOut, User, Bell, CalendarClock, ChevronDown, Users } from 'lucide-react'
import { authApi, isAuthenticated, getCurrentUser, removeToken, setCurrentUser } from '@/services/authApi'
import { LLMSelector } from '@/components/LLMSelector'
import { FloatingAssistant } from '@/components/FloatingAssistant'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const DashboardPage = lazy(() =>
  import('@/pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
)
const PortfolioPage = lazy(() =>
  import('@/pages/PortfolioPage').then((module) => ({ default: module.PortfolioPage })),
)
const AdvicePage = lazy(() =>
  import('@/pages/AdvicePage').then((module) => ({ default: module.AdvicePage })),
)
const NotificationSettingsPage = lazy(() =>
  import('@/pages/NotificationSettingsPage').then((module) => ({ default: module.NotificationSettingsPage })),
)
const AdminUsersPage = lazy(() =>
  import('@/pages/AdminUsersPage').then((module) => ({ default: module.AdminUsersPage })),
)
const AdminSchedulerPage = lazy(() =>
  import('@/pages/AdminSchedulerPage').then((module) => ({ default: module.AdminSchedulerPage })),
)
const LoginPage = lazy(() => import('@/pages/LoginPage'))

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/login" replace />
}

function AppContent() {
  const location = useLocation()
  const navigate = useNavigate()
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

  useEffect(() => {
    if (!authed) return

    authApi.getMe()
      .then((nextUser) => {
        setCurrentUser(nextUser)
        setUser(nextUser)
      })
      .catch(() => {
        // 401 is handled globally by the auth API interceptor.
      })
  }, [authed])

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
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-primary/30 hover:text-primary">
                        <User className="h-4 w-4" />
                        <span className="max-w-28 truncate sm:max-w-none">{user?.username}</span>
                        <ChevronDown className="h-4 w-4 text-slate-400" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-56">
                      <DropdownMenuLabel>
                        <div className="flex flex-col">
                          <span className="text-sm font-semibold">{user?.username}</span>
                          <span className="text-xs font-normal text-muted-foreground">个人设置与账户操作</span>
                        </div>
                      </DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={() => navigate('/notifications')}>
                        <Bell className="h-4 w-4" />
                        通知设置
                      </DropdownMenuItem>
                      {user?.is_admin && (
                        <>
                          <DropdownMenuItem onSelect={() => navigate('/admin/users')}>
                            <Users className="h-4 w-4" />
                            账号管理
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => navigate('/admin/scheduler')}>
                            <CalendarClock className="h-4 w-4" />
                            定时任务
                          </DropdownMenuItem>
                        </>
                      )}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={handleLogout} className="text-red-600 focus:text-red-600">
                        <LogOut className="h-4 w-4" />
                        退出登录
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
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
            <Route path="/notifications" element={<PrivateRoute><NotificationSettingsPage /></PrivateRoute>} />
            <Route path="/admin/users" element={<PrivateRoute><AdminUsersPage /></PrivateRoute>} />
            <Route path="/admin/scheduler" element={<PrivateRoute><AdminSchedulerPage /></PrivateRoute>} />
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

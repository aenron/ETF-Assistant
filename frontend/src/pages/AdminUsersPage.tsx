import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, Save, ShieldCheck, ShieldOff, UserCheck, UserX } from 'lucide-react'

import { adminApi, type AdminUser, type AdminUserUpdate } from '@/services/api'
import { getCurrentUser } from '@/services/authApi'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

export function AdminUsersPage() {
  const currentUser = getCurrentUser()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [balanceDrafts, setBalanceDrafts] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [savingUserId, setSavingUserId] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const loadUsers = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const res = await adminApi.listUsers()
      setUsers(res.data)
      setBalanceDrafts(Object.fromEntries(
        res.data.map((user) => [user.id, user.account_balance == null ? '' : String(user.account_balance)]),
      ))
    } catch (error: any) {
      console.error('Failed to load users:', error)
      setMessage(error.response?.data?.detail || '加载账号列表失败')
    } finally {
      setLoading(false)
    }
  }

  const updateUser = async (user: AdminUser, data: AdminUserUpdate) => {
    setSavingUserId(user.id)
    setMessage(null)
    try {
      const res = await adminApi.updateUser(user.id, data)
      setUsers((prev) => prev.map((item) => item.id === user.id ? res.data : item))
      setBalanceDrafts((prev) => ({
        ...prev,
        [user.id]: res.data.account_balance == null ? '' : String(res.data.account_balance),
      }))
    } catch (error: any) {
      console.error('Failed to update user:', error)
      setMessage(error.response?.data?.detail || '更新账号失败')
    } finally {
      setSavingUserId(null)
    }
  }

  const saveBalance = async (user: AdminUser) => {
    const rawValue = balanceDrafts[user.id]?.trim()
    if (!rawValue) {
      setMessage('账户金额不能为空')
      return
    }
    const value = Number(rawValue)
    if (!Number.isFinite(value) || value < 0) {
      setMessage('账户金额必须是大于等于 0 的数字')
      return
    }
    await updateUser(user, { account_balance: value })
  }

  useEffect(() => {
    loadUsers()
  }, [])

  const activeCount = users.filter((user) => user.is_active).length
  const adminCount = users.filter((user) => user.is_admin).length

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">账号管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">管理账号启用状态、管理员权限和账户金额。</p>
        </div>
        <Button variant="outline" onClick={loadUsers} disabled={loading} className="w-full sm:w-auto">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {message && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {message}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">账号总数</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{users.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">启用账号</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeCount}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">管理员</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{adminCount}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>账号列表</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载账号中...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="px-2 py-3 text-left">账号</th>
                    <th className="px-2 py-3 text-left">邮箱</th>
                    <th className="px-2 py-3 text-left">角色</th>
                    <th className="px-2 py-3 text-left">状态</th>
                    <th className="px-2 py-3 text-left">账户金额</th>
                    <th className="px-2 py-3 text-left">创建时间</th>
                    <th className="px-2 py-3 text-center">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const isSelf = currentUser?.id === user.id
                    const saving = savingUserId === user.id
                    return (
                      <tr key={user.id} className="border-b align-top">
                        <td className="px-2 py-3">
                          <div className="font-medium">{user.username}</div>
                          {isSelf && <div className="mt-1 text-xs text-muted-foreground">当前登录账号</div>}
                        </td>
                        <td className="px-2 py-3 text-muted-foreground">{user.email || '-'}</td>
                        <td className="px-2 py-3">
                          <Badge variant="outline" className={user.is_admin ? 'border-blue-300 bg-blue-50 text-blue-700' : ''}>
                            {user.is_admin ? '管理员' : '普通用户'}
                          </Badge>
                        </td>
                        <td className="px-2 py-3">
                          <Badge variant="outline" className={user.is_active ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-slate-300 bg-slate-50 text-slate-600'}>
                            {user.is_active ? '已启用' : '已禁用'}
                          </Badge>
                        </td>
                        <td className="px-2 py-3">
                          <div className="flex min-w-40 items-center gap-2">
                            <Input
                              type="number"
                              min="0"
                              step="0.01"
                              value={balanceDrafts[user.id] ?? ''}
                              onChange={(event) => setBalanceDrafts((prev) => ({ ...prev, [user.id]: event.target.value }))}
                              placeholder="账户金额"
                            />
                            <Button size="icon" variant="outline" onClick={() => saveBalance(user)} disabled={saving}>
                              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                            </Button>
                          </div>
                        </td>
                        <td className="px-2 py-3 text-xs text-muted-foreground">{formatTime(user.created_at)}</td>
                        <td className="px-2 py-3">
                          <div className="flex min-w-56 flex-col gap-3">
                            <label className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                              <span className="inline-flex items-center gap-2 text-sm">
                                {user.is_active ? <UserCheck className="h-4 w-4 text-emerald-600" /> : <UserX className="h-4 w-4 text-slate-500" />}
                                启用账号
                              </span>
                              <Switch
                                checked={user.is_active}
                                disabled={saving || isSelf}
                                onCheckedChange={(checked) => updateUser(user, { is_active: checked })}
                              />
                            </label>
                            <label className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                              <span className="inline-flex items-center gap-2 text-sm">
                                {user.is_admin ? <ShieldCheck className="h-4 w-4 text-blue-600" /> : <ShieldOff className="h-4 w-4 text-slate-500" />}
                                管理员
                              </span>
                              <Switch
                                checked={user.is_admin}
                                disabled={saving || isSelf}
                                onCheckedChange={(checked) => updateUser(user, { is_admin: checked })}
                              />
                            </label>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

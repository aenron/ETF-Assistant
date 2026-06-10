import { useEffect, useState } from 'react'
import { Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'

import { adminApi, type DcaIndexMapping, type DcaIndexMappingCreate } from '@/services/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

const emptyForm: DcaIndexMappingCreate = {
  etf_code: '',
  keyword: '',
  index_symbol: '',
  index_name: '',
  enabled: true,
}

export function AdminDcaIndexMappingPage() {
  const [items, setItems] = useState<DcaIndexMapping[]>([])
  const [form, setForm] = useState<DcaIndexMappingCreate>(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error'>('success')

  const loadItems = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const res = await adminApi.listDcaIndexMappings()
      setItems(res.data)
    } catch (error: any) {
      console.error('Failed to load DCA index mappings:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '加载宽基估值映射失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItems()
  }, [])

  const saveNew = async () => {
    if (!form.etf_code?.trim() && !form.keyword?.trim()) {
      setMessageTone('error')
      setMessage('ETF代码和名称关键词至少填写一个')
      return
    }
    if (!form.index_symbol.trim()) {
      setMessageTone('error')
      setMessage('指数代码不能为空')
      return
    }
    setSaving(true)
    setMessage(null)
    try {
      const payload = {
        ...form,
        etf_code: form.etf_code?.trim() || null,
        keyword: form.keyword?.trim() || null,
        index_symbol: form.index_symbol.trim(),
        index_name: form.index_name?.trim() || null,
      }
      const res = await adminApi.createDcaIndexMapping(payload)
      setItems((prev) => [res.data, ...prev])
      setForm(emptyForm)
      setMessageTone('success')
      setMessage('映射已新增')
    } catch (error: any) {
      console.error('Failed to create DCA index mapping:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '新增映射失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleEnabled = async (item: DcaIndexMapping, enabled: boolean) => {
    setBusyId(item.id)
    setMessage(null)
    try {
      const res = await adminApi.updateDcaIndexMapping(item.id, { enabled })
      setItems((prev) => prev.map((current) => current.id === item.id ? res.data : current))
    } catch (error: any) {
      console.error('Failed to update DCA index mapping:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '更新映射失败')
    } finally {
      setBusyId(null)
    }
  }

  const deleteItem = async (item: DcaIndexMapping) => {
    if (!window.confirm(`确认删除映射 ${item.etf_code || item.keyword || item.index_symbol}？`)) return
    setBusyId(item.id)
    setMessage(null)
    try {
      await adminApi.deleteDcaIndexMapping(item.id)
      setItems((prev) => prev.filter((current) => current.id !== item.id))
      setMessageTone('success')
      setMessage('映射已删除')
    } catch (error: any) {
      console.error('Failed to delete DCA index mapping:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '删除映射失败')
    } finally {
      setBusyId(null)
    }
  }

  const messageClassName = messageTone === 'success'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-red-200 bg-red-50 text-red-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">宽基估值映射</h1>
          <p className="mt-1 text-sm text-muted-foreground">配置持仓 ETF 对应的中证指数估值代码，红绿灯估值轨会优先使用这里的配置。</p>
        </div>
        <Button variant="outline" onClick={loadItems} disabled={loading} className="w-full sm:w-auto">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {message && <div className={`rounded-xl border px-4 py-3 text-sm ${messageClassName}`}>{message}</div>}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5 text-primary" />
            新增映射
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-[150px_1fr_150px_1fr_auto] md:items-end">
            <label className="space-y-1.5">
              <span className="text-sm font-medium">ETF代码</span>
              <Input value={form.etf_code || ''} onChange={(e) => setForm({ ...form, etf_code: e.target.value })} placeholder="510300" />
            </label>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">名称关键词</span>
              <Input value={form.keyword || ''} onChange={(e) => setForm({ ...form, keyword: e.target.value })} placeholder="沪深300" />
            </label>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">指数代码</span>
              <Input value={form.index_symbol} onChange={(e) => setForm({ ...form, index_symbol: e.target.value })} placeholder="000300" />
            </label>
            <label className="space-y-1.5">
              <span className="text-sm font-medium">指数名称</span>
              <Input value={form.index_name || ''} onChange={(e) => setForm({ ...form, index_name: e.target.value })} placeholder="沪深300" />
            </label>
            <Button onClick={saveNew} disabled={saving}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              保存
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">匹配优先级：ETF代码精确匹配优先，其次名称关键词匹配，最后使用系统内置兜底映射。</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>映射列表</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载映射中...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="px-2 py-3 text-left">ETF代码</th>
                    <th className="px-2 py-3 text-left">关键词</th>
                    <th className="px-2 py-3 text-left">指数</th>
                    <th className="px-2 py-3 text-left">状态</th>
                    <th className="px-2 py-3 text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b last:border-0">
                      <td className="px-2 py-3 font-mono">{item.etf_code || '-'}</td>
                      <td className="px-2 py-3">{item.keyword || '-'}</td>
                      <td className="px-2 py-3">
                        <div className="font-mono">{item.index_symbol}</div>
                        <div className="text-xs text-muted-foreground">{item.index_name || '-'}</div>
                      </td>
                      <td className="px-2 py-3">
                        <Badge variant="outline" className={item.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-600'}>
                          {item.enabled ? '启用' : '停用'}
                        </Badge>
                      </td>
                      <td className="px-2 py-3">
                        <div className="flex justify-end gap-2">
                          <label className="flex items-center gap-2 rounded-lg border px-3 py-2">
                            <span className="text-xs">启用</span>
                            <Switch checked={item.enabled} disabled={busyId === item.id} onCheckedChange={(checked) => toggleEnabled(item, checked)} />
                          </label>
                          <Button variant="outline" size="sm" onClick={() => deleteItem(item)} disabled={busyId === item.id}>
                            <Trash2 className="mr-2 h-4 w-4" />
                            删除
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {items.length === 0 && <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">暂无映射配置</div>}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'

import { adminApi, type IndustryFundamentalSnapshot } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

function formatPct(value: number | null | undefined) {
  return value == null ? '-' : `${value.toFixed(2)}%`
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

export function AdminIndustryFundamentalsPage() {
  const [items, setItems] = useState<IndustryFundamentalSnapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshingKey, setRefreshingKey] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const loadItems = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const res = await adminApi.listIndustryFundamentals()
      setItems(res.data.items)
    } catch (error: any) {
      console.error('Failed to load industry fundamentals:', error)
      setMessage(error.response?.data?.detail || '加载行业基本面失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItems()
  }, [])

  const refresh = async (key?: string) => {
    setRefreshingKey(key || '__all__')
    setMessage(null)
    try {
      const res = await adminApi.refreshIndustryFundamentals(key)
      setItems(res.data.items)
      setMessage(`已刷新 ${res.data.refreshed} 个行业`)
    } catch (error: any) {
      console.error('Failed to refresh industry fundamentals:', error)
      setMessage(error.response?.data?.detail || '刷新行业基本面失败')
    } finally {
      setRefreshingKey(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">行业基本面</h1>
          <p className="mt-1 text-sm text-muted-foreground">查看行业 ROE、利润增速、盈利预测和缓存采集状态。</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" onClick={loadItems} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            重新加载
          </Button>
          <Button onClick={() => refresh()} disabled={refreshingKey != null}>
            {refreshingKey === '__all__' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            刷新全部
          </Button>
        </div>
      </div>

      {message && <div className="rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">{message}</div>}

      {loading ? (
        <Card><CardContent className="flex items-center justify-center py-12 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载行业基本面中...</CardContent></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((item) => {
            const data = item.data
            return (
              <Card key={item.key}>
                <CardHeader className="space-y-2">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle>{item.industry_name}</CardTitle>
                      <p className="mt-1 text-xs text-muted-foreground">{item.em_industry} · {item.key}</p>
                    </div>
                    <Badge variant={item.cached ? 'default' : 'outline'}>{item.cached ? '已缓存' : '无缓存'}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">景气度</div><div className="mt-1 font-mono text-lg font-semibold">{data?.score?.toFixed(1) ?? '-'}</div></div>
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">ROE</div><div className="mt-1 font-mono">{formatPct(data?.roe)}</div></div>
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">净利润同比</div><div className="mt-1 font-mono">{formatPct(data?.net_profit_growth)}</div></div>
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">营收同比</div><div className="mt-1 font-mono">{formatPct(data?.revenue_growth)}</div></div>
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">EPS预测增速</div><div className="mt-1 font-mono">{formatPct(data?.forecast_eps_growth)}</div></div>
                    <div className="rounded-md bg-muted/40 p-3"><div className="text-xs text-muted-foreground">买入/增持</div><div className="mt-1 font-mono">{formatPct(data?.positive_rating_ratio)}</div></div>
                  </div>
                  <div className="text-xs text-muted-foreground">缓存时间：{formatDateTime(item.cached_at)} · 样本股：{item.sample_symbols.join(' / ')}</div>
                  {data?.errors?.length ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">{data.errors.join('；')}</div> : null}
                  <div className="flex justify-end">
                    <Button variant="outline" size="sm" onClick={() => refresh(item.key)} disabled={refreshingKey != null}>
                      {refreshingKey === item.key ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                      刷新行业
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

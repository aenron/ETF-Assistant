import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Loader2, Plus, RefreshCw, Search, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { EtfDetailModal } from '@/components/EtfDetailModal'
import {
  watchlistApi,
  type AssetType,
  type PortfolioWithMarket,
  type WatchlistItem,
} from '@/services/api'
import { compareBeijingTimeDesc, formatBeijingTime } from '@/utils/time'

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  etf: '场内基金',
  stock: '股票',
  otc_fund: '场外基金',
  cash: '现金',
  money_fund: '货币基金',
}

const FILTERS: Array<{ value: 'all' | AssetType | 'holding'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'stock', label: '股票' },
  { value: 'etf', label: '场内基金' },
  { value: 'otc_fund', label: '场外基金' },
  { value: 'holding', label: '已持有' },
]

function formatNumber(value: number | null | undefined, digits = 2, emptyText = '-') {
  if (value == null || !Number.isFinite(value)) return emptyText
  return value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function formatPrice(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value) || value <= 0) return '-'
  return value.toFixed(value >= 100 ? 2 : 3)
}

function formatAmount(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '-'
  if (Math.abs(value) >= 100000000) return `${formatNumber(value / 100000000, 2)}亿`
  if (Math.abs(value) >= 10000) return `${formatNumber(value / 10000, 2)}万`
  return formatNumber(value, 0)
}

function changeClass(value: number | null | undefined) {
  if (value == null || value === 0) return 'text-slate-600'
  return value > 0 ? 'text-red-600' : 'text-emerald-600'
}

function toPortfolioLike(item: WatchlistItem): PortfolioWithMarket {
  const now = new Date().toISOString()
  return {
    id: -item.id,
    etf_code: item.code,
    asset_type: item.asset_type,
    shares: 0,
    cost_price: item.current_price && item.current_price > 0 ? item.current_price : 1,
    buy_date: null,
    note: item.note,
    dca_track_override: null,
    created_at: item.created_at || now,
    updated_at: item.updated_at || now,
    etf_name: item.name,
    current_price: item.current_price,
    change_pct: item.change_pct,
    market_refreshed_at: item.market_refreshed_at,
    market_value: item.holding_market_value,
    pnl: null,
    pnl_pct: null,
    today_pnl: null,
    today_pnl_pct: null,
    holding_days: null,
    dca_track: null,
    dca_light: null,
    dca_label: null,
    dca_action: null,
    dca_reason: null,
    dca_next_trigger_price: null,
    dca_valuation_percentile: null,
    dca_valuation_pe: null,
    dca_valuation_pb: null,
    dca_valuation_pe_percentile: null,
    dca_valuation_pb_percentile: null,
    dca_valuation_sample_size: null,
    dca_trend_ma20: null,
    dca_trend_ma20_slope_pct: null,
    dca_trend_distance_pct: null,
    dca_trend_atr14: null,
    dca_trend_atr_band_pct: null,
    dca_trend_ma60: null,
    dca_trend_ma60_slope_pct: null,
    dca_trend_ma120: null,
    dca_trend_ma120_slope_pct: null,
    dca_trend_volume_ratio: null,
    dca_trend_atr_multiplier: null,
    dca_decision_steps: null,
    dca_candidate_light: null,
    dca_candidate_confirm_count: null,
    dca_quality_score: null,
    dca_green_trigger_price: null,
    dca_deep_green_trigger_price: null,
    dca_budget_multiplier: null,
    dca_budget_label: null,
    cross_border_risk: null,
    factor_score: null,
    trend_signal: null,
  }
}

export function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error' | 'neutral'>('neutral')
  const [filter, setFilter] = useState<'all' | AssetType | 'holding'>('all')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [query, setQuery] = useState('')
  const [form, setForm] = useState({ code: '', name: '', asset_type: 'etf' as AssetType, note: '' })
  const [detailItem, setDetailItem] = useState<WatchlistItem | null>(null)

  const latestMarketRefreshAt = items
    .map((item) => item.market_refreshed_at)
    .filter((value): value is string => Boolean(value))
    .sort(compareBeijingTimeDesc)
    .at(0) ?? null

  const stats = useMemo(() => {
    const quoted = items.filter((item) => item.current_price != null && item.current_price > 0)
    const up = quoted.filter((item) => (item.change_pct ?? 0) > 0).length
    const down = quoted.filter((item) => (item.change_pct ?? 0) < 0).length
    const holding = items.filter((item) => item.is_holding).length
    const top = [...quoted].sort((a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity))[0] ?? null
    return { quoted: quoted.length, up, down, holding, top }
  }, [items])

  const visibleItems = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return items.filter((item) => {
      if (filter === 'holding' && !item.is_holding) return false
      if (filter !== 'all' && filter !== 'holding' && item.asset_type !== filter) return false
      if (!keyword) return true
      return item.code.toLowerCase().includes(keyword) || (item.name || '').toLowerCase().includes(keyword)
    })
  }, [filter, items, query])

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await watchlistApi.getList()
      setItems(res.data)
    } catch (error) {
      console.error('Failed to fetch watchlist:', error)
      setMessageTone('error')
      setMessage('加载自选列表失败')
    } finally {
      setLoading(false)
    }
  }

  const refreshListSilently = async () => {
    try {
      const res = await watchlistApi.getList()
      setItems(res.data)
    } catch (error) {
      console.error('Failed to auto refresh watchlist:', error)
    }
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const code = form.code.trim().toUpperCase()
    if (!code) {
      setMessageTone('error')
      setMessage('请填写代码')
      return
    }
    setSubmitting(true)
    setMessageTone('neutral')
    setMessage('正在添加自选...')
    try {
      await watchlistApi.create({
        code,
        name: form.name.trim() || undefined,
        asset_type: form.asset_type,
        note: form.note.trim() || undefined,
      })
      setForm({ code: '', name: '', asset_type: form.asset_type, note: '' })
      setMessageTone('success')
      setMessage('已添加到自选')
      await fetchData()
    } catch (error) {
      console.error('Failed to create watchlist item:', error)
      setMessageTone('error')
      setMessage('添加自选失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    setMessageTone('neutral')
    setMessage('正在刷新自选行情...')
    try {
      const res = await watchlistApi.refreshAll()
      setMessageTone(res.data.success ? 'success' : 'error')
      setMessage(res.data.message || (res.data.success ? '刷新完成' : '刷新失败'))
      await fetchData()
    } catch (error) {
      console.error('Failed to refresh watchlist:', error)
      setMessageTone('error')
      setMessage('刷新自选行情失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleDelete = async (item: WatchlistItem) => {
    if (!window.confirm(`确认移除自选 ${item.code}？`)) return
    try {
      await watchlistApi.delete(item.id)
      setMessageTone('success')
      setMessage('已移除自选')
      await fetchData()
    } catch (error) {
      console.error('Failed to delete watchlist item:', error)
      setMessageTone('error')
      setMessage('移除自选失败')
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = window.setInterval(refreshListSilently, 60000)
    return () => window.clearInterval(timer)
  }, [autoRefresh])

  const messageClassName = messageTone === 'success'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : messageTone === 'error'
      ? 'border-red-200 bg-red-50 text-red-700'
      : 'border-slate-200 bg-slate-50 text-slate-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">自选行情</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            当前使用行情时间：{formatBeijingTime(latestMarketRefreshAt, {
              year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
            }, '暂无缓存行情')}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="inline-flex h-10 items-center justify-center gap-2 rounded-md border bg-background px-3 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary"
            />
            自动刷新60秒
          </label>
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} className="w-full sm:w-10">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button onClick={handleRefresh} disabled={refreshing || items.length === 0}>
            {refreshing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            刷新行情
          </Button>
        </div>
      </div>

      {message && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${messageClassName}`}>{message}</div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">自选数量</p>
          <p className="mt-2 text-2xl font-semibold">{items.length}</p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">有行情</p>
          <p className="mt-2 text-2xl font-semibold">{stats.quoted}</p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">上涨 / 下跌</p>
          <p className="mt-2 text-2xl font-semibold"><span className="text-red-600">{stats.up}</span> / <span className="text-emerald-600">{stats.down}</span></p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-sm text-muted-foreground">今日领涨</p>
          <p className="mt-2 truncate text-lg font-semibold">{stats.top ? `${stats.top.code} ${stats.top.change_pct != null ? `${stats.top.change_pct >= 0 ? '+' : ''}${stats.top.change_pct.toFixed(2)}%` : ''}` : '-'}</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border bg-card p-4">
        <div className="grid gap-3 md:grid-cols-[1fr,1fr,160px,1.4fr,auto] md:items-end">
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">代码</span>
            <input
              value={form.code}
              onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus:border-primary"
              placeholder="例如 510300 / 600519"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">名称</span>
            <input
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus:border-primary"
              placeholder="可选"
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">类型</span>
            <select
              value={form.asset_type}
              onChange={(event) => setForm((prev) => ({ ...prev, asset_type: event.target.value as AssetType }))}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus:border-primary"
            >
              {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">备注</span>
            <input
              value={form.note}
              onChange={(event) => setForm((prev) => ({ ...prev, note: event.target.value }))}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus:border-primary"
              placeholder="观察理由、目标价等"
            />
          </label>
          <Button type="submit" disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
            添加
          </Button>
        </div>
      </form>

      <div className="rounded-lg border bg-card">
        <div className="flex flex-col gap-3 border-b p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${filter === item.value ? 'border-primary bg-primary/10 text-primary' : 'border-slate-200 bg-background text-slate-600 hover:text-primary'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="relative block lg:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm outline-none focus:border-primary"
              placeholder="搜索代码或名称"
            />
          </label>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="border-b bg-muted/40 text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">品种</th>
                <th className="px-4 py-3 text-right font-medium">现价</th>
                <th className="px-4 py-3 text-right font-medium">涨跌幅</th>
                <th className="px-4 py-3 text-right font-medium">今开/高/低</th>
                <th className="px-4 py-3 text-right font-medium">成交额</th>
                <th className="px-4 py-3 text-right font-medium">成交量</th>
                <th className="px-4 py-3 text-right font-medium">溢价率</th>
                <th className="px-4 py-3 font-medium">持仓</th>
                <th className="px-4 py-3 font-medium">更新时间</th>
                <th className="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />加载中...</td></tr>
              ) : visibleItems.length === 0 ? (
                <tr><td colSpan={10} className="px-4 py-12 text-center text-muted-foreground">暂无自选，先添加一个代码</td></tr>
              ) : visibleItems.map((item) => (
                <tr
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setDetailItem(item)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setDetailItem(item)
                    }
                  }}
                  className="cursor-pointer border-b last:border-0 hover:bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30"
                >
                  <td className="px-4 py-3">
                    <div className="font-mono font-semibold">{item.code}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="max-w-40 truncate">{item.name || '-'}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{ASSET_TYPE_LABELS[item.asset_type] || item.asset_type}</span>
                    </div>
                    {item.note && <div className="mt-1 max-w-56 truncate text-xs text-muted-foreground">{item.note}</div>}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold">{formatPrice(item.current_price)}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${changeClass(item.change_pct)}`}>
                    {item.change_pct != null ? `${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(2)}%` : '-'}
                  </td>
                  <td className="px-4 py-3 text-right text-muted-foreground">
                    {formatPrice(item.open_price)} / {formatPrice(item.high_price)} / {formatPrice(item.low_price)}
                  </td>
                  <td className="px-4 py-3 text-right">{formatAmount(item.amount)}</td>
                  <td className="px-4 py-3 text-right">{formatAmount(item.volume)}</td>
                  <td className={`px-4 py-3 text-right ${changeClass(item.premium_rate)}`}>
                    {item.premium_rate != null ? `${item.premium_rate >= 0 ? '+' : ''}${item.premium_rate.toFixed(2)}%` : '-'}
                  </td>
                  <td className="px-4 py-3">
                    {item.is_holding ? (
                      <div>
                        <span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">已持有</span>
                        <div className="mt-1 text-xs text-muted-foreground">市值 {formatNumber(item.holding_market_value, 2)}</div>
                      </div>
                    ) : <span className="text-muted-foreground">未持有</span>}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {formatBeijingTime(item.market_refreshed_at, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }, '-')}
                  </td>
                  <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDelete(item)}
                        className="text-red-600 hover:text-red-700"
                        title="移除自选"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {detailItem && (
        <EtfDetailModal portfolio={toPortfolioLike(detailItem)} onClose={() => setDetailItem(null)} />
      )}
    </div>
  )
}

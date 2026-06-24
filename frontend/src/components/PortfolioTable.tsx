import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { portfolioApi, marketApi, adviceApi, type PortfolioWithMarket, type EtfSearchResult, type AdviceResponse, type MarketHistoryResponse, type PortfolioDcaSignalHistoryItem } from '@/services/api'
import { Plus, Pencil, Trash2, Search, Lightbulb, RefreshCw, Eye, Clock, HelpCircle } from 'lucide-react'
import { buildTradeSignalFromHistory, EtfDetailModal, type BenchmarkKey, type TradeSignal } from './EtfDetailModal'
import { ConfirmDialog } from './ConfirmDialog'
import { AdviceEventContextPanel } from './AdviceEventContextPanel'
import { formatBeijingTime } from '@/utils/time'
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface PortfolioTableProps {
  portfolios: PortfolioWithMarket[]
  onRefresh: () => void
}

type PortfolioSortKey = 'shares' | 'market_value' | 'today_pnl_pct' | 'advice'
type SortDirection = 'asc' | 'desc'

export function PortfolioTable({ portfolios, onRefresh }: PortfolioTableProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<EtfSearchResult[]>([])
  const [formData, setFormData] = useState({
    etf_code: '',
    shares: '',
    cost_price: '',
    buy_date: '',
    note: '',
    dca_track_override: '',
  })
  const [adviceLoading, setAdviceLoading] = useState<number | null>(null)
  const [currentAdvice, setCurrentAdvice] = useState<AdviceResponse | null>(null)
  const [showAdviceModal, setShowAdviceModal] = useState(false)
  const [refreshingCode, setRefreshingCode] = useState<string | null>(null)
  const [detailPortfolio, setDetailPortfolio] = useState<PortfolioWithMarket | null>(null)
  const [tradeSignalHistory, setTradeSignalHistory] = useState<Record<string, MarketHistoryResponse>>({})
  const [benchmarkHistory, setBenchmarkHistory] = useState<Record<BenchmarkKey, MarketHistoryResponse | null>>({ hs300: null, csiA500: null })
  const [deleteTarget, setDeleteTarget] = useState<PortfolioWithMarket | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [showDcaHelp, setShowDcaHelp] = useState(false)
  const [dcaDetailPortfolio, setDcaDetailPortfolio] = useState<PortfolioWithMarket | null>(null)
  const [dcaHistory, setDcaHistory] = useState<MarketHistoryResponse | null>(null)
  const [dcaHistoryLoading, setDcaHistoryLoading] = useState(false)
  const [dcaSignalHistory, setDcaSignalHistory] = useState<PortfolioDcaSignalHistoryItem[]>([])
  const [dcaSignalHistoryLoading, setDcaSignalHistoryLoading] = useState(false)
  const [showDcaChangesOnly, setShowDcaChangesOnly] = useState(false)
  const [sortConfig, setSortConfig] = useState<{ key: PortfolioSortKey; direction: SortDirection }>({ key: 'today_pnl_pct', direction: 'desc' })

  useEffect(() => {
    fetchTradeSignalData()
  }, [portfolios.map((item) => item.etf_code).join(',')])


  const fetchTradeSignalData = async () => {
    const codes = Array.from(new Set(portfolios.map((item) => item.etf_code).filter(Boolean)))
    if (codes.length === 0) {
      setTradeSignalHistory({})
      return
    }

    try {
      const [hs300Res, csiA500Res] = await Promise.allSettled([
        marketApi.getHistory('000300', 60),
        marketApi.getHistory('000510', 60),
      ])
      setBenchmarkHistory({
        hs300: hs300Res.status === 'fulfilled' ? hs300Res.value.data : null,
        csiA500: csiA500Res.status === 'fulfilled' ? csiA500Res.value.data : null,
      })

      const results = await Promise.allSettled(codes.map((code) => marketApi.getHistory(code, 60)))
      const nextHistory: Record<string, MarketHistoryResponse> = {}
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          nextHistory[codes[index]] = result.value.data
        }
      })
      setTradeSignalHistory(nextHistory)
    } catch (e) {
      console.error('Failed to fetch trade signal histories:', e)
    }
  }

  const getTradeSignal = (code: string): TradeSignal | null => {
    const history = tradeSignalHistory[code]
    if (!history) return null
    return buildTradeSignalFromHistory(history, benchmarkHistory)
  }


  const getAdviceSortValue = (signal: TradeSignal | null) => {
    if (!signal) return -1
    const rank: Record<string, number> = {
      clear: 80,
      reduce: 70,
      take_profit: 60,
      watch: signal.label === '等待回踩' ? 50 : signal.label === '观察修复' ? 45 : 40,
      insufficient: 20,
      buy: signal.label === '正常买入' ? 10 : 15,
    }
    return rank[signal.action] ?? 0
  }

  const sortPortfolios = (items: PortfolioWithMarket[]) => {
    return items.slice().sort((a, b) => {
      const signalA = getTradeSignal(a.etf_code)
      const signalB = getTradeSignal(b.etf_code)
      const valueA = sortConfig.key === 'shares'
        ? a.shares
        : sortConfig.key === 'market_value'
          ? a.market_value ?? -Infinity
          : sortConfig.key === 'today_pnl_pct'
            ? a.today_pnl_pct ?? -Infinity
            : getAdviceSortValue(signalA)
      const valueB = sortConfig.key === 'shares'
        ? b.shares
        : sortConfig.key === 'market_value'
          ? b.market_value ?? -Infinity
          : sortConfig.key === 'today_pnl_pct'
            ? b.today_pnl_pct ?? -Infinity
            : getAdviceSortValue(signalB)
      const result = valueA === valueB ? a.etf_code.localeCompare(b.etf_code) : valueA - valueB
      return sortConfig.direction === 'asc' ? result : -result
    })
  }

  const sortedPortfolios = sortPortfolios(portfolios)

  const handleSort = (key: PortfolioSortKey) => {
    setSortConfig((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }

  const sortLabel = (key: PortfolioSortKey) => sortConfig.key === key ? (sortConfig.direction === 'desc' ? ' ↓' : ' ↑') : ''

  const SortHeader = ({ sortKey, align = 'right', children }: { sortKey: PortfolioSortKey; align?: 'left' | 'right' | 'center'; children: React.ReactNode }) => {
    const alignClass = align === 'right' ? 'justify-end text-right' : align === 'center' ? 'justify-center text-center' : 'justify-start text-left'
    return (
      <button
        type="button"
        onClick={() => handleSort(sortKey)}
        className={`inline-flex w-full items-center gap-1 font-medium text-foreground hover:text-primary ${alignClass}`}
        title="点击排序"
      >
        <span>{children}</span>
        <span className="text-[10px] text-muted-foreground">{sortLabel(sortKey)}</span>
      </button>
    )
  }

  const handleSearch = async () => {
    if (searchQuery.length >= 1) {
      const res = await marketApi.searchEtf(searchQuery)
      setSearchResults(res.data)
    }
  }

  const handleSelectEtf = (etf: EtfSearchResult) => {
    setFormData({ ...formData, etf_code: etf.code })
    setSearchResults([])
    setSearchQuery('')
  }

  const resetPortfolioForm = () => {
    setShowForm(false)
    setEditingId(null)
    setSearchResults([])
    setSearchQuery('')
    setFormData({ etf_code: '', shares: '', cost_price: '', buy_date: '', note: '', dca_track_override: '' })
  }

  const openCreateForm = () => {
    setEditingId(null)
    setSearchResults([])
    setSearchQuery('')
    setFormData({ etf_code: '', shares: '', cost_price: '', buy_date: '', note: '', dca_track_override: '' })
    setShowForm(true)
  }

  const handleSubmit = async () => {
    const data = {
      etf_code: formData.etf_code,
      shares: parseFloat(formData.shares),
      cost_price: parseFloat(formData.cost_price),
      buy_date: formData.buy_date || undefined,
      note: formData.note || undefined,
      dca_track_override: formData.dca_track_override || undefined,
    }

    if (editingId) {
      await portfolioApi.update(editingId, data)
    } else {
      await portfolioApi.create(data)
    }

    resetPortfolioForm()
    onRefresh()
  }

  const handleEdit = (p: PortfolioWithMarket) => {
    setEditingId(p.id)
    setSearchResults([])
    setSearchQuery('')
    setFormData({
      etf_code: p.etf_code,
      shares: p.shares.toString(),
      cost_price: p.cost_price.toString(),
      buy_date: p.buy_date || '',
      note: p.note || '',
      dca_track_override: p.dca_track_override || '',
    })
    setShowForm(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget || deleting) return

    setDeleting(true)
    try {
      await portfolioApi.delete(deleteTarget.id)
      setDeleteTarget(null)
      onRefresh()
    } finally {
      setDeleting(false)
    }
  }


  const getCrossBorderRiskClass = (level?: string | null) => {
    if (level === 'high') return 'border-red-200 bg-red-50 text-red-700'
    if (level === 'medium') return 'border-amber-200 bg-amber-50 text-amber-700'
    return 'border-slate-200 bg-slate-50 text-slate-600'
  }

  const formatCrossBorderRiskLevel = (level?: string | null) => {
    if (level === 'high') return '高风险'
    if (level === 'medium') return '中风险'
    return '低风险'
  }

  const handleGetAdvice = async (portfolioId: number) => {
    setAdviceLoading(portfolioId)
    try {
      const res = await adviceApi.generateForPortfolio(portfolioId)
      setCurrentAdvice(res.data)
      setShowAdviceModal(true)
    } catch (error: any) {
      console.error('Failed to get advice:', error)
      const errorMsg = error?.code === 'ECONNABORTED' 
        ? '请求超时，AI正在搜索最新信息，请稍后重试' 
        : '获取建议失败，请稍后重试'
      alert(errorMsg)
    } finally {
      setAdviceLoading(null)
    }
  }

  const handleRegenerateAdvice = async () => {
    if (!currentAdvice) return
    // Find portfolio id by etf_code
    const portfolio = portfolios.find(p => p.etf_code === currentAdvice.etf_code)
    if (portfolio) {
      await handleGetAdvice(portfolio.id)
    }
  }

  const handleRefreshQuote = async (code: string) => {
    setRefreshingCode(code)
    try {
      const res = await marketApi.refreshQuote(code)
      if (res.data.success) {
        onRefresh()
      } else {
        alert(res.data.message || '刷新失败')
      }
    } catch (error) {
      console.error('Failed to refresh quote:', error)
      alert('刷新行情失败')
    } finally {
      setRefreshingCode(null)
    }
  }

  const getAdviceTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      buy: '买入',
      sell: '卖出',
      hold: '持有',
      reduce: '减仓',
      add: '加仓',
    }
    return labels[type] || type
  }

  const getAdviceTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      buy: 'text-red-500',
      sell: 'text-green-500',
      hold: 'text-blue-500',
      reduce: 'text-green-500',
      add: 'text-red-500',
    }
    return colors[type] || 'text-gray-500'
  }

  const formatMarketRefreshedAt = (value: string | null) => {
    return formatBeijingTime(value, {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }, '未缓存')
  }

  const formatPnl = (pnl: number | null, pnlPct: number | null) => {
    if (pnl === null || pnl === undefined || pnlPct === null || pnlPct === undefined) {
      return '-'
    }
    return `${pnl.toFixed(2)}（${pnlPct.toFixed(2)}%）`
  }

  const getPnlColorClass = (value: number | null | undefined) => {
    return value && value > 0 ? 'text-red-500' : value && value < 0 ? 'text-green-500' : ''
  }

  const resolveDcaDisplayLight = (light: string | null | undefined, label?: string | null) => {
    if (label?.startsWith('深绿')) return 'deep_green'
    if (label?.startsWith('绿灯')) return 'green'
    if (label?.startsWith('黄灯')) return 'yellow'
    if (label?.startsWith('红灯')) return 'red'
    return light
  }

  const getDcaLightClass = (light: string | null | undefined, label?: string | null) => {
    const displayLight = resolveDcaDisplayLight(light, label)
    if (displayLight === 'green' || displayLight === 'deep_green') return 'bg-emerald-500'
    if (displayLight === 'red') return 'bg-red-500'
    return 'bg-amber-400'
  }

  const getDcaTextClass = (light: string | null | undefined, label?: string | null) => {
    const displayLight = resolveDcaDisplayLight(light, label)
    if (displayLight === 'green' || displayLight === 'deep_green') return 'text-emerald-700'
    if (displayLight === 'red') return 'text-red-700'
    return 'text-amber-700'
  }

  const formatDcaMeta = (p: PortfolioWithMarket) => {
    if (p.dca_valuation_percentile != null) {
      const peText = p.dca_valuation_pe != null ? `PE ${p.dca_valuation_pe.toFixed(2)} · ` : ''
      const pbText = p.dca_valuation_pb != null ? `PB ${p.dca_valuation_pb.toFixed(2)} · ` : ''
      return `${peText}${pbText}综合分位 ${p.dca_valuation_percentile.toFixed(1)}%`
    }
    return p.dca_next_trigger_price == null ? '暂无触发价' : `触发价 ${p.dca_next_trigger_price.toFixed(3)}`
  }


  const openDcaDetail = (event: React.MouseEvent, p: PortfolioWithMarket) => {
    event.stopPropagation()
    setDcaSignalHistory([])
    setDcaHistory(null)
    setDcaDetailPortfolio(p)
  }

  const formatDcaTrack = (track: string | null | undefined) => {
    if (track === 'valuation') return '估值轨'
    if (track === 'trend') return '趋势轨'
    if (track === 'disabled') return '已关闭'
    return '自动识别'
  }


  const formatDcaLight = (light: string | null | undefined) => {
    if (light === 'deep_green') return '深绿'
    if (light === 'green') return '绿灯'
    if (light === 'yellow') return '黄灯'
    if (light === 'red') return '红灯'
    return '无'
  }

  const metricPercent = (value: number | null | undefined, fallback = 0) => {
    if (value == null || Number.isNaN(value)) return fallback
    return Math.max(0, Math.min(100, value))
  }


  const lightScore = (light: string | null | undefined) => {
    if (light === 'deep_green') return 4
    if (light === 'green') return 3
    if (light === 'yellow') return 2
    if (light === 'red') return 1
    return 0
  }

  const lightTimelineData = dcaSignalHistory
    .slice()
    .reverse()
    .map((item) => ({
      date: formatBeijingTime(item.scanned_at, { month: '2-digit', day: '2-digit' }, '-'),
      formal: lightScore(item.persisted_light),
      signal: lightScore(item.signal_light),
      label: `${formatDcaLight(item.persisted_light)} / ${formatDcaLight(item.signal_light)}`,
    }))

  const latestDcaSignal = dcaSignalHistory[0]
  const currentDcaTrack = dcaDetailPortfolio?.dca_track || latestDcaSignal?.metrics?.track || null
  const isValuationTrack = currentDcaTrack === 'valuation'
  const isTrendTrack = currentDcaTrack === 'trend'
  const dcaDataSourceText = latestDcaSignal
    ? `最近扫描 ${formatBeijingTime(latestDcaSignal.scanned_at)}`
    : dcaSignalHistoryLoading
      ? '正在读取最近扫描记录'
      : '暂无扫描时间'


  const chronologicalDcaHistory = dcaSignalHistory.slice().reverse()
  const dcaHistoryChangeIds = new Set<number>()
  chronologicalDcaHistory.forEach((item, index) => {
    const previous = chronologicalDcaHistory[index - 1]
    if (!previous || previous.persisted_light !== item.persisted_light || previous.signal_light !== item.signal_light) {
      dcaHistoryChangeIds.add(item.id)
    }
  })
  const filteredDcaSignalHistory = showDcaChangesOnly
    ? dcaSignalHistory.filter((item) => dcaHistoryChangeIds.has(item.id))
    : dcaSignalHistory
  const dcaLightCounts = dcaSignalHistory.reduce<Record<string, number>>((acc, item) => {
    const key = item.persisted_light || 'unknown'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const dcaChangeCount = dcaSignalHistory.filter((item) => dcaHistoryChangeIds.has(item.id)).length
  const latestDcaMetrics = dcaSignalHistory[0]?.metrics || {}
  const previousDcaMetrics = dcaSignalHistory[1]?.metrics || {}
  const formatMetricDelta = (current: unknown, previous: unknown, suffix = '') => {
    const currentNumber = Number(current)
    const previousNumber = Number(previous)
    if (!Number.isFinite(currentNumber) || !Number.isFinite(previousNumber)) return '-'
    const delta = currentNumber - previousNumber
    const sign = delta > 0 ? '+' : ''
    return `${sign}${delta.toFixed(2)}${suffix}`
  }

  const buildMiniChartData = (history: MarketHistoryResponse | null) => {
    const data = history?.data || []
    return data.map((item, index) => {
      const ma20Window = data.slice(Math.max(0, index - 19), index + 1)
      const ma20 = ma20Window.length === 20
        ? ma20Window.reduce((sum, current) => sum + current.close_price, 0) / 20
        : null
      return {
        date: item.trade_date.slice(5),
        close: item.close_price,
        ma20,
      }
    })
  }

  useEffect(() => {
    if (!dcaDetailPortfolio) {
      setDcaHistory(null)
      return
    }
    let cancelled = false
    setDcaHistoryLoading(true)
    setDcaSignalHistoryLoading(true)
    marketApi.getHistory(dcaDetailPortfolio.etf_code, 60)
      .then((res) => {
        if (!cancelled) setDcaHistory(res.data)
      })
      .catch((error) => {
        console.error('Failed to fetch DCA mini chart history:', error)
        if (!cancelled) setDcaHistory(null)
      })
      .finally(() => {
        if (!cancelled) setDcaHistoryLoading(false)
      })
    portfolioApi.getDcaHistory(dcaDetailPortfolio.id, 30)
      .then((res) => {
        if (!cancelled) setDcaSignalHistory(res.data)
      })
      .catch((error) => {
        console.error('Failed to fetch DCA signal history:', error)
        if (!cancelled) setDcaSignalHistory([])
      })
      .finally(() => {
        if (!cancelled) setDcaSignalHistoryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [dcaDetailPortfolio?.etf_code])

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <CardTitle>持仓列表</CardTitle>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-8 w-8"
            title="定投灯说明"
            onClick={() => setShowDcaHelp(true)}
          >
            <HelpCircle className="h-4 w-4" />
          </Button>
        </div>
        <Button className="w-full sm:w-auto" onClick={openCreateForm}>
          <Plus className="h-4 w-4 mr-2" />
          新增持仓
        </Button>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 md:hidden">
          {sortedPortfolios.map((p) => {
            const tradeSignal = getTradeSignal(p.etf_code)
            return (
              <div key={p.id} className="rounded-xl border bg-background p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-base font-semibold">{p.etf_code}</div>
                    <div className="mt-1 text-sm text-muted-foreground">{p.etf_name || '-'}</div>
                    {p.current_price == null && (
                      <div className="mt-2 inline-flex rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">行情缓存刷新中</div>
                    )}
                    <button
                      type="button"
                      className={`mt-2 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium transition-colors hover:bg-muted ${getDcaTextClass(p.dca_light, p.dca_label)}`}
                      title={p.dca_reason || undefined}
                      onClick={(event) => openDcaDetail(event, p)}
                    >
                      <span className={`h-2.5 w-2.5 rounded-full ${getDcaLightClass(p.dca_light, p.dca_label)}`} />
                      <span>{p.dca_label || '定投灯待计算'}</span>
                    </button>
                  </div>
                  {tradeSignal ? (
                    <button type="button" onClick={() => setDetailPortfolio(p)} className="shrink-0">
                      <Badge
                        variant="outline"
                        className={`text-xs ${tradeSignal.toneClassName}`}
                        title="查看详情"
                      >
                        {tradeSignal.label}
                      </Badge>
                    </button>
                  ) : (
                    <span className="shrink-0 text-xs text-muted-foreground">计算中</span>
                  )}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground">持有份额</div>
                    <div className="mt-1 font-medium">{p.shares.toLocaleString()}</div>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground">当前价格</div>
                    <div className="mt-1 font-medium">{p.current_price?.toFixed(3) || '-'}</div>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground">市值</div>
                    <div className="mt-1 font-medium">{p.market_value?.toFixed(2) || '-'}</div>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground">盈亏</div>
                    <div className={`${getPnlColorClass(p.pnl)} mt-1 font-medium`}>
                      {formatPnl(p.pnl, p.pnl_pct)}
                    </div>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <div className="text-xs text-muted-foreground">今日涨跌</div>
                    <div className={`${getPnlColorClass(p.today_pnl)} mt-1 font-medium`}>
                      {formatPnl(p.today_pnl, p.today_pnl_pct)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>行情时间</span>
                  <span>{formatMarketRefreshedAt(p.market_refreshed_at)}</span>
                </div>

                <div className="mt-4 grid grid-cols-5 gap-2">
                  <Button
                    size="icon"
                    variant="outline"
                    onClick={() => setDetailPortfolio(p)}
                    title="查看详情"
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="outline"
                    onClick={() => handleGetAdvice(p.id)}
                    disabled={adviceLoading === p.id}
                    title="生成AI建议"
                  >
                    <Lightbulb className={`h-4 w-4 ${adviceLoading === p.id ? 'animate-pulse text-yellow-500' : ''}`} />
                  </Button>
                  <Button
                    size="icon"
                    variant="outline"
                    onClick={() => handleRefreshQuote(p.etf_code)}
                    disabled={refreshingCode === p.etf_code}
                    title="刷新行情"
                  >
                    <RefreshCw className={`h-4 w-4 ${refreshingCode === p.etf_code ? 'animate-spin' : ''}`} />
                  </Button>
                  <Button size="icon" variant="outline" onClick={() => handleEdit(p)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button size="icon" variant="outline" onClick={() => setDeleteTarget(p)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>
            )
          })}

          {portfolios.length === 0 && (
            <div className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
              暂无持仓数据，点击“新增持仓”开始添加
            </div>
          )}
        </div>

        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b">
                <th className="text-left py-3 px-2">代码</th>
                <th className="text-left py-3 px-2">名称</th>
                <th className="text-right py-3 px-2"><SortHeader sortKey="shares">份额</SortHeader></th>
                <th className="text-right py-3 px-2">成本/现价</th>
                <th className="text-right py-3 px-2"><SortHeader sortKey="market_value">市值</SortHeader></th>
                <th className="text-right py-3 px-2">盈亏</th>
                <th className="text-right py-3 px-2"><SortHeader sortKey="today_pnl_pct">今日涨跌</SortHeader></th>
                <th className="text-left py-3 px-2">定投灯</th>
                <th className="text-center py-3 px-2"><SortHeader sortKey="advice" align="center">建议</SortHeader></th>
                <th className="text-center py-3 px-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {sortedPortfolios.map((p) => {
                const tradeSignal = getTradeSignal(p.etf_code)
                return (
                <tr key={p.id} className="border-b hover:bg-muted/50 cursor-pointer" onClick={() => setDetailPortfolio(p)}>
                  <td className="py-3 px-2 font-mono">{p.etf_code}</td>
                  <td className="py-3 px-2">
                    <div>{p.etf_name || '-'}</div>
                    {p.current_price == null && <div className="mt-1 text-xs text-amber-700">行情缓存刷新中</div>}
                  </td>
                  <td className="py-3 px-2 text-right">{p.shares.toLocaleString()}</td>
                  <td className="py-3 px-2 text-right">
                    <div className="flex flex-col items-end">
                      <span>{p.cost_price.toFixed(4)} / {p.current_price?.toFixed(3) || '-'}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {formatMarketRefreshedAt(p.market_refreshed_at)}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 px-2 text-right">{p.market_value?.toFixed(2) || '-'}</td>
                  <td className={`py-3 px-2 text-right ${getPnlColorClass(p.pnl)}`}>
                    {formatPnl(p.pnl, p.pnl_pct)}
                  </td>
                  <td className={`py-3 px-2 text-right ${getPnlColorClass(p.today_pnl)}`}>
                    {formatPnl(p.today_pnl, p.today_pnl_pct)}
                  </td>
                  <td className="py-3 px-2" title={p.dca_reason || undefined} onClick={e => e.stopPropagation()}>
                    <button
                      type="button"
                      className={`inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium transition-colors hover:bg-muted ${getDcaTextClass(p.dca_light, p.dca_label)}`}
                      onClick={(event) => openDcaDetail(event, p)}
                    >
                      <span className={`h-2.5 w-2.5 rounded-full ${getDcaLightClass(p.dca_light, p.dca_label)}`} />
                      <span>{p.dca_label || '待计算'}</span>
                    </button>
                    <div className="mt-1 max-w-44 truncate text-[10px] text-muted-foreground">
                      {p.dca_budget_label || p.dca_action || '-'} · {formatDcaMeta(p)}
                    </div>
                  </td>
                  <td className="py-3 px-2 text-center" onClick={e => e.stopPropagation()}>
                    {tradeSignal ? (
                      <button type="button" onClick={() => setDetailPortfolio(p)} className="inline-flex">
                        <Badge
                          variant="outline"
                          className={`text-xs ${tradeSignal.toneClassName}`}
                          title="查看详情"
                        >
                          {tradeSignal.label}
                        </Badge>
                      </button>
                    ) : (
                      <span className="text-xs text-muted-foreground">计算中</span>
                    )}
                  </td>
                  <td className="py-3 px-2 text-center" onClick={e => e.stopPropagation()}>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => setDetailPortfolio(p)}
                      title="查看详情"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => handleGetAdvice(p.id)}
                      disabled={adviceLoading === p.id}
                      title="生成AI建议"
                    >
                      <Lightbulb className={`h-4 w-4 ${adviceLoading === p.id ? 'animate-pulse text-yellow-500' : ''}`} />
                    </Button>
                    <Button 
                      size="icon" 
                      variant="ghost" 
                      onClick={() => handleRefreshQuote(p.etf_code)}
                      disabled={refreshingCode === p.etf_code}
                      title="刷新行情"
                    >
                      <RefreshCw className={`h-4 w-4 ${refreshingCode === p.etf_code ? 'animate-spin' : ''}`} />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => handleEdit(p)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => setDeleteTarget(p)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </td>
                </tr>
                )
              })}
              {portfolios.length === 0 && (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-muted-foreground">
                    暂无持仓数据，点击"新增持仓"开始添加
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 建议弹窗 */}
        <Dialog open={showForm} onOpenChange={(open) => { if (open) setShowForm(true); else resetPortfolioForm() }}>
          <DialogContent className="max-h-[88vh] w-[calc(100vw-2rem)] max-w-2xl overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editingId ? '编辑持仓' : '新增持仓'}</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="relative sm:col-span-2">
                <label className="text-sm font-medium">ETF代码</label>
                <div className="flex gap-2">
                  <Input
                    value={formData.etf_code}
                    onChange={(e) => setFormData({ ...formData, etf_code: e.target.value })}
                    placeholder="输入代码搜索"
                    disabled={!!editingId}
                  />
                  <Button size="icon" variant="outline" onClick={handleSearch} disabled={!!editingId}>
                    <Search className="h-4 w-4" />
                  </Button>
                </div>
                {searchResults.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full max-h-48 overflow-auto rounded-md border bg-background shadow-lg">
                    {searchResults.map((etf) => (
                      <div
                        key={etf.code}
                        className="cursor-pointer px-3 py-2 hover:bg-muted"
                        onClick={() => handleSelectEtf(etf)}
                      >
                        <span className="font-mono">{etf.code}</span>
                        <span className="ml-2 text-muted-foreground">{etf.name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="text-sm font-medium">份额</label>
                <Input
                  type="number"
                  value={formData.shares}
                  onChange={(e) => setFormData({ ...formData, shares: e.target.value })}
                  placeholder="持有份额"
                />
              </div>
              <div>
                <label className="text-sm font-medium">成本价</label>
                <Input
                  type="number"
                  step="0.0001"
                  value={formData.cost_price}
                  onChange={(e) => setFormData({ ...formData, cost_price: e.target.value })}
                  placeholder="成本价"
                />
              </div>
              <div>
                <label className="text-sm font-medium">买入日期</label>
                <Input
                  type="date"
                  value={formData.buy_date}
                  onChange={(e) => setFormData({ ...formData, buy_date: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium">资产轨道</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={formData.dca_track_override}
                  onChange={(e) => setFormData({ ...formData, dca_track_override: e.target.value })}
                >
                  <option value="">自动识别</option>
                  <option value="valuation">估值轨</option>
                  <option value="trend">趋势轨</option>
                  <option value="disabled">关闭定投灯</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="text-sm font-medium">备注</label>
                <Input
                  value={formData.note}
                  onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                  placeholder="备注"
                />
              </div>
            </div>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button className="w-full sm:w-auto" variant="outline" onClick={resetPortfolioForm}>取消</Button>
              <Button className="w-full sm:w-auto" onClick={handleSubmit}>{editingId ? '保存修改' : '创建持仓'}</Button>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={showDcaHelp} onOpenChange={setShowDcaHelp}>
          <DialogContent className="max-h-[88vh] w-[calc(100vw-2rem)] max-w-3xl overflow-y-auto">
            <DialogHeader>
              <DialogTitle>定投红绿灯说明</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 text-sm text-slate-700">
              <section className="rounded-lg border bg-slate-50 p-4">
                <h3 className="font-semibold text-slate-900">灯色含义</h3>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <div><span className="font-medium text-emerald-700">深绿</span>：估值极低或机会强，允许更高倍率加仓。</div>
                  <div><span className="font-medium text-emerald-700">绿灯</span>：满足加仓条件，可执行增强定投。</div>
                  <div><span className="font-medium text-amber-700">黄灯</span>：条件不完整，只做基础定投或观察。</div>
                  <div><span className="font-medium text-red-700">红灯</span>：估值过高或趋势走弱，暂停新增定投。</div>
                </div>
              </section>

              <section className="rounded-lg border p-4">
                <h3 className="font-semibold text-slate-900">估值轨</h3>
                <p className="mt-2 text-muted-foreground">用于沪深300、中证500、中证A500、科创50等宽基资产。系统保存历史 PE/PB，计算当前估值在历史中的位置。</p>
                <div className="mt-3 rounded-md bg-muted/40 p-3 font-mono text-xs text-slate-700">综合分位 = 0.6 * PE分位 + 0.4 * PB分位</div>
                <p className="mt-2 text-muted-foreground">样本不足时不会给强信号；PB 缺失时会退化为 PE 分位。</p>
              </section>

              <section className="rounded-lg border p-4">
                <h3 className="font-semibold text-slate-900">宽基 MA20 确认</h3>
                <p className="mt-2 text-muted-foreground">低估不等于马上加仓。若价格低于 MA20 且 MA20 下行，系统会把低估信号降为黄灯，等待趋势企稳；若价格站回 MA20 或趋势未明显走坏，才保留绿灯或深绿。</p>
              </section>

              <section className="rounded-lg border p-4">
                <h3 className="font-semibold text-slate-900">趋势轨</h3>
                <p className="mt-2 text-muted-foreground">用于行业主题、商品、海外 ETF 等更依赖趋势的资产。核心判断是价格是否高于 MA20、MA20 是否上行。</p>
              </section>

              <section className="rounded-lg border p-4">
                <h3 className="font-semibold text-slate-900">ATR 波动率过滤</h3>
                <p className="mt-2 text-muted-foreground">趋势轨不会在价格过度偏离时追高。系统计算 ATR14，只有价格距离 MA20 不超过 1.5 倍 ATR 时，才认为是可接受的右侧回踩；超过则黄灯等待回落。</p>
              </section>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={!!dcaDetailPortfolio} onOpenChange={(open) => !open && setDcaDetailPortfolio(null)}>
          <DialogContent className="max-h-[88vh] w-[calc(100vw-2rem)] max-w-3xl overflow-y-auto">
            {dcaDetailPortfolio && (
              <>
                <DialogHeader>
                  <DialogTitle>定投灯决策详情</DialogTitle>
                </DialogHeader>
                <Tabs defaultValue="current" className="mt-2">
                  <TabsList className="grid w-full grid-cols-2">
                    <TabsTrigger value="current">当前详情</TabsTrigger>
                    <TabsTrigger value="history">历史记录</TabsTrigger>
                  </TabsList>
                  <TabsContent value="current" className="space-y-4 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-base font-semibold">{dcaDetailPortfolio.etf_code}</span>
                    <span className="text-muted-foreground">{dcaDetailPortfolio.etf_name || '-'}</span>
                    <Badge variant="outline" className={`${getDcaTextClass(dcaDetailPortfolio.dca_light, dcaDetailPortfolio.dca_label)} border-current`}>
                      {dcaDetailPortfolio.dca_label || '定投灯待计算'}
                    </Badge>
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3.5 w-3.5" />
                      {dcaDataSourceText}
                    </span>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">资产轨道</div>
                      <div className="mt-1 font-medium">{formatDcaTrack(currentDcaTrack)}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">建议动作</div>
                      <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_action || '-'}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">资金倍率</div>
                      <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_budget_label || (dcaDetailPortfolio.dca_budget_multiplier != null ? `${dcaDetailPortfolio.dca_budget_multiplier}x` : '-')}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">{isTrendTrack ? '趋势触发价' : '下一触发价'}</div>
                      <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_next_trigger_price?.toFixed(3) || '-'}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">正式灯色</div>
                      <div className={`mt-1 font-medium ${getDcaTextClass(dcaDetailPortfolio.dca_light, dcaDetailPortfolio.dca_label)}`}>{formatDcaLight(dcaDetailPortfolio.dca_light)}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">候选灯色</div>
                      <div className={`mt-1 font-medium ${getDcaTextClass(dcaDetailPortfolio.dca_candidate_light)}`}>{formatDcaLight(dcaDetailPortfolio.dca_candidate_light)}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">确认进度</div>
                      <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_candidate_confirm_count ? `${Math.min(dcaDetailPortfolio.dca_candidate_confirm_count, 2)}/2` : '-'}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/30 p-3">
                      <div className="text-xs text-muted-foreground">信号评分</div>
                      <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_quality_score?.toFixed(1) || '-'}</div>
                    </div>
                    {isValuationTrack && (
                      <>
                        <div className="rounded-lg border bg-muted/30 p-3">
                          <div className="text-xs text-muted-foreground">浅绿估值触发价</div>
                          <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_green_trigger_price?.toFixed(3) || '-'}</div>
                        </div>
                        <div className="rounded-lg border bg-muted/30 p-3">
                          <div className="text-xs text-muted-foreground">深绿估值触发价</div>
                          <div className="mt-1 font-medium">{dcaDetailPortfolio.dca_deep_green_trigger_price?.toFixed(3) || '-'}</div>
                        </div>
                      </>
                    )}
                  </div>

                  {dcaDetailPortfolio.cross_border_risk?.is_cross_border && (
                    <section className={`rounded-lg border p-4 ${getCrossBorderRiskClass(dcaDetailPortfolio.cross_border_risk.risk_level)}`}>
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <h3 className="font-semibold">跨境风控</h3>
                        <Badge variant="outline" className="border-current bg-background/70">{formatCrossBorderRiskLevel(dcaDetailPortfolio.cross_border_risk.risk_level)} · {dcaDetailPortfolio.cross_border_risk.action}</Badge>
                      </div>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                        <div className="rounded-md bg-background/70 p-3">
                          <div className="text-xs opacity-80">建议上限</div>
                          <div className="mt-1 font-mono">{(dcaDetailPortfolio.cross_border_risk.max_position_hint * 100).toFixed(0)}%</div>
                        </div>
                        <div className="rounded-md bg-background/70 p-3">
                          <div className="text-xs opacity-80">倍率折减</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.cross_border_risk.budget_multiplier_adjustment.toFixed(2)}x</div>
                        </div>
                        <div className="rounded-md bg-background/70 p-3">
                          <div className="text-xs opacity-80">IOPV</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.cross_border_risk.iopv?.toFixed(4) || '-'}</div>
                        </div>
                        <div className="rounded-md bg-background/70 p-3">
                          <div className="text-xs opacity-80">溢价率</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.cross_border_risk.premium_rate != null ? `${dcaDetailPortfolio.cross_border_risk.premium_rate.toFixed(2)}%` : '-'}</div>
                        </div>
                        <div className="rounded-md bg-background/70 p-3">
                          <div className="text-xs opacity-80">风险标签</div>
                          <div className="mt-1">{dcaDetailPortfolio.cross_border_risk.risk_tags.join(' / ') || '-'}</div>
                        </div>
                      </div>
                      <p className="mt-3 leading-6">{dcaDetailPortfolio.cross_border_risk.reason}</p>
                      {dcaDetailPortfolio.cross_border_risk.warnings.length > 0 && (
                        <ul className="mt-3 space-y-1.5 text-sm">
                          {dcaDetailPortfolio.cross_border_risk.warnings.map((warning) => (
                            <li key={warning}>• {warning}</li>
                          ))}
                        </ul>
                      )}
                    </section>
                  )}

                  {dcaDetailPortfolio.factor_score?.enabled && (
                    <section className="rounded-lg border p-4">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <h3 className="font-semibold">行业四因子评分</h3>
                        <Badge variant="outline">{dcaDetailPortfolio.factor_score.rating} · {dcaDetailPortfolio.factor_score.action}</Badge>
                      </div>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">综合分</div>
                          <div className="mt-1 text-lg font-semibold">{dcaDetailPortfolio.factor_score.total_score.toFixed(1)}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">宏观</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.macro_score.toFixed(1)}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">技术</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.technical_score.toFixed(1)}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">情绪</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.sentiment_score.toFixed(1)}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">景气度</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.prosperity_score.toFixed(1)}</div>
                        </div>
                      </div>
                      <div className="mt-3 grid gap-3 sm:grid-cols-3">
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">20日动量</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.momentum20 != null ? `${dcaDetailPortfolio.factor_score.momentum20.toFixed(2)}%` : '-'}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">成交额</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.amount != null ? `${(dcaDetailPortfolio.factor_score.amount / 100000000).toFixed(2)}亿` : '-'}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">流动性</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.factor_score.liquidity_score != null ? dcaDetailPortfolio.factor_score.liquidity_score.toFixed(1) : '-'}</div>
                        </div>
                      </div>
                      <p className="mt-3 leading-6 text-muted-foreground">{dcaDetailPortfolio.factor_score.reason}</p>
                      {dcaDetailPortfolio.factor_score.factors.length > 0 && (
                        <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
                          {dcaDetailPortfolio.factor_score.factors.map((factor) => (
                            <li key={factor}>• {factor}</li>
                          ))}
                        </ul>
                      )}
                    </section>
                  )}

                  <section className="rounded-lg border p-4">
                    <h3 className="font-semibold">决策路径</h3>
                    {dcaDetailPortfolio.dca_decision_steps?.length ? (
                      <ol className="mt-3 space-y-2">
                        {dcaDetailPortfolio.dca_decision_steps.map((step, index) => (
                          <li key={`${step}-${index}`} className="flex gap-2 text-sm text-muted-foreground">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-medium text-slate-700">{index + 1}</span>
                            <span>{step}</span>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="mt-2 text-muted-foreground">暂无结构化决策路径</p>
                    )}
                  </section>

                  <section className="rounded-lg border p-4">
                    <h3 className="font-semibold">决策原因</h3>
                    <p className="mt-2 leading-6 text-muted-foreground">{dcaDetailPortfolio.dca_reason || '暂无详细原因'}</p>
                  </section>

                  {isValuationTrack && (
                    <section className="rounded-lg border p-4">
                      <h3 className="font-semibold">估值拆解</h3>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">PE / PE分位</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_valuation_pe?.toFixed(2) || '-'} / {dcaDetailPortfolio.dca_valuation_pe_percentile?.toFixed(1) || '-'}%</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">PB / PB分位</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_valuation_pb?.toFixed(2) || '-'} / {dcaDetailPortfolio.dca_valuation_pb_percentile?.toFixed(1) || '-'}%</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">综合分位</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_valuation_percentile?.toFixed(1) || '-'}%</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">估值样本</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_valuation_sample_size ?? '-'}</div>
                        </div>
                      </div>
                    </section>
                  )}

                  <section className="rounded-lg border p-4">
                    <h3 className="font-semibold">趋势指标</h3>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">MA20 / 斜率</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_ma20?.toFixed(3) || '-'} / {dcaDetailPortfolio.dca_trend_ma20_slope_pct?.toFixed(2) || '-'}%</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">MA60 / 斜率</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_ma60?.toFixed(3) || '-'} / {dcaDetailPortfolio.dca_trend_ma60_slope_pct?.toFixed(2) || '-'}%</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">MA120 / 斜率</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_ma120?.toFixed(3) || '-'} / {dcaDetailPortfolio.dca_trend_ma120_slope_pct?.toFixed(2) || '-'}%</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">距离MA20</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_distance_pct?.toFixed(2) || '-'}%</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">ATR14 / 倍数</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_atr14?.toFixed(3) || '-'} / {dcaDetailPortfolio.dca_trend_atr_multiplier?.toFixed(1) || '-'}x</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">ATR容忍区间</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_atr_band_pct?.toFixed(2) || '-'}%</div>
                      </div>
                      <div className="rounded-md bg-muted/40 p-3">
                        <div className="text-xs text-muted-foreground">量能确认</div>
                        <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_trend_volume_ratio?.toFixed(2) || '-'}x</div>
                      </div>
                    </div>
                  </section>

                  <section className="rounded-lg border p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <h3 className="font-semibold">近 60 日迷你图</h3>
                      <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-full bg-blue-600" />收盘价</span>
                        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-4 rounded-full bg-amber-500" />MA20</span>
                        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-emerald-500" />触发价</span>
                        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-red-500" />当前价</span>
                      </div>
                    </div>
                    <div className="mt-4 h-56 rounded-md border bg-white p-2">
                      {dcaHistoryLoading ? (
                        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">加载走势中...</div>
                      ) : buildMiniChartData(dcaHistory).length > 0 ? (
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={buildMiniChartData(dcaHistory)} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                            <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" minTickGap={24} />
                            <YAxis tick={{ fontSize: 10 }} domain={["dataMin", "dataMax"]} />
                            <Tooltip formatter={(value: number, name: string) => [Number(value).toFixed(3), name === '收盘价' ? '收盘价' : name === 'MA20' ? 'MA20' : name]} labelFormatter={(label) => `日期 ${label}`} />
                            <Line type="monotone" dataKey="close" name="收盘价" stroke="#2563eb" strokeWidth={1.8} dot={false} isAnimationActive={false} />
                            <Line type="monotone" dataKey="ma20" name="MA20" stroke="#f59e0b" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                            {dcaDetailPortfolio.dca_next_trigger_price != null && (
                              <ReferenceLine y={dcaDetailPortfolio.dca_next_trigger_price} stroke="#10b981" strokeDasharray="4 4" label={{ value: '触发价', fontSize: 10, fill: '#059669' }} />
                            )}
                            {dcaDetailPortfolio.current_price != null && (
                              <ReferenceLine y={dcaDetailPortfolio.current_price} stroke="#ef4444" strokeDasharray="3 3" label={{ value: '当前价', fontSize: 10, fill: '#dc2626' }} />
                            )}
                          </LineChart>
                        </ResponsiveContainer>
                      ) : (
                        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">暂无走势数据</div>
                      )}
                    </div>
                  </section>

                  <section className="rounded-lg border p-4">
                    <h3 className="font-semibold">图表数据</h3>
                    <div className="mt-4 space-y-4">
                      {dcaDetailPortfolio.dca_valuation_percentile != null && (
                        <div>
                          <div className="mb-1 flex items-center justify-between text-xs">
                            <span>综合估值分位</span>
                            <span>{dcaDetailPortfolio.dca_valuation_percentile.toFixed(1)}%</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-emerald-500" style={{ width: `${metricPercent(dcaDetailPortfolio.dca_valuation_percentile)}%` }} />
                          </div>
                        </div>
                      )}
                      <div className="grid gap-3 sm:grid-cols-3">
                        {isValuationTrack && (
                          <div className="rounded-md bg-muted/40 p-3">
                            <div className="text-xs text-muted-foreground">PE / PB</div>
                            <div className="mt-1 font-mono">{dcaDetailPortfolio.dca_valuation_pe?.toFixed(2) || '-'} / {dcaDetailPortfolio.dca_valuation_pb?.toFixed(2) || '-'}</div>
                          </div>
                        )}
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">成本 / 现价</div>
                          <div className="mt-1 font-mono">{dcaDetailPortfolio.cost_price.toFixed(4)} / {dcaDetailPortfolio.current_price?.toFixed(3) || '-'}</div>
                        </div>
                        <div className="rounded-md bg-muted/40 p-3">
                          <div className="text-xs text-muted-foreground">持仓盈亏</div>
                          <div className={`mt-1 font-mono ${getPnlColorClass(dcaDetailPortfolio.pnl)}`}>{formatPnl(dcaDetailPortfolio.pnl, dcaDetailPortfolio.pnl_pct)}</div>
                        </div>
                      </div>
                      {dcaDetailPortfolio.dca_quality_score != null && (
                        <div>
                          <div className="mb-1 flex items-center justify-between text-xs">
                            <span>信号质量评分</span>
                            <span>{dcaDetailPortfolio.dca_quality_score.toFixed(1)}</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-violet-500" style={{ width: `${metricPercent(dcaDetailPortfolio.dca_quality_score)}%` }} />
                          </div>
                        </div>
                      )}
                      {dcaDetailPortfolio.current_price != null && dcaDetailPortfolio.dca_next_trigger_price != null && (
                        <div>
                          <div className="mb-1 flex items-center justify-between text-xs">
                            <span>现价相对触发价</span>
                            <span>{dcaDetailPortfolio.current_price.toFixed(3)} / {dcaDetailPortfolio.dca_next_trigger_price.toFixed(3)}</span>
                          </div>
                          <div className="h-2 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-blue-500" style={{ width: `${metricPercent(dcaDetailPortfolio.current_price / dcaDetailPortfolio.dca_next_trigger_price * 100) }%` }} />
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                </TabsContent>
                  <TabsContent value="history" className="space-y-3 text-sm">
                    {dcaSignalHistoryLoading ? (
                      <div className="rounded-lg border py-10 text-center text-muted-foreground">加载历史记录中...</div>
                    ) : dcaSignalHistory.length > 0 ? (
                      <div className="space-y-3">
                        <div className="grid gap-3 sm:grid-cols-4">
                          <div className="rounded-lg border bg-muted/30 p-3">
                            <div className="text-xs text-muted-foreground">扫描次数</div>
                            <div className="mt-1 text-lg font-semibold">{dcaSignalHistory.length}</div>
                          </div>
                          <div className="rounded-lg border bg-muted/30 p-3">
                            <div className="text-xs text-muted-foreground">变化点</div>
                            <div className="mt-1 text-lg font-semibold">{dcaChangeCount}</div>
                          </div>
                          <div className="rounded-lg border bg-muted/30 p-3">
                            <div className="text-xs text-muted-foreground">绿灯/深绿</div>
                            <div className="mt-1 text-lg font-semibold text-emerald-700">{(dcaLightCounts.green || 0) + (dcaLightCounts.deep_green || 0)}</div>
                          </div>
                          <div className="rounded-lg border bg-muted/30 p-3">
                            <div className="text-xs text-muted-foreground">黄灯/红灯</div>
                            <div className="mt-1 text-lg font-semibold text-amber-700">{(dcaLightCounts.yellow || 0) + (dcaLightCounts.red || 0)}</div>
                          </div>
                        </div>

                        <div className="rounded-lg border p-4">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                              <h3 className="font-semibold">本次相对上次</h3>
                              <p className="mt-1 text-xs text-muted-foreground">比较最近两次扫描的核心指标变化。</p>
                            </div>
                            <div className="grid gap-2 text-xs sm:grid-cols-4">
                              <div className="rounded bg-muted/40 p-2">价格 <span className="font-mono">{formatMetricDelta(dcaSignalHistory[0]?.price, dcaSignalHistory[1]?.price)}</span></div>
                              <div className="rounded bg-muted/40 p-2">分位 <span className="font-mono">{formatMetricDelta(latestDcaMetrics.valuation_percentile, previousDcaMetrics.valuation_percentile, '%')}</span></div>
                              <div className="rounded bg-muted/40 p-2">MA20斜率 <span className="font-mono">{formatMetricDelta(latestDcaMetrics.trend_ma20_slope_pct, previousDcaMetrics.trend_ma20_slope_pct, '%')}</span></div>
                              <div className="rounded bg-muted/40 p-2">量能 <span className="font-mono">{formatMetricDelta(latestDcaMetrics.trend_volume_ratio, previousDcaMetrics.trend_volume_ratio, 'x')}</span></div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-lg border p-4">
                          <div className="flex items-center justify-between gap-3">
                            <h3 className="font-semibold">灯色时间轴</h3>
                            <span className="text-xs text-muted-foreground">正式灯色 / 本次信号</span>
                          </div>
                          <div className="mt-3 h-44">
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart data={lightTimelineData} margin={{ top: 8, right: 12, left: -22, bottom: 0 }}>
                                <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={18} />
                                <YAxis tick={{ fontSize: 10 }} domain={[0, 4]} ticks={[1, 2, 3, 4]} tickFormatter={(value) => ['', '红', '黄', '绿', '深绿'][Number(value)] || ''} />
                                <Tooltip formatter={(value: number, name: string) => [formatDcaLight(value === 4 ? 'deep_green' : value === 3 ? 'green' : value === 2 ? 'yellow' : value === 1 ? 'red' : null), name === 'formal' ? '正式灯色' : '本次信号']} />
                                <Line type="stepAfter" dataKey="formal" name="正式灯色" stroke="#2563eb" strokeWidth={1.8} dot={false} isAnimationActive={false} />
                                <Line type="stepAfter" dataKey="signal" name="本次信号" stroke="#f59e0b" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                        <div className="flex flex-col gap-2 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between">
                          <div>
                            <h3 className="font-semibold">扫描明细</h3>
                            <p className="mt-1 text-xs text-muted-foreground">{showDcaChangesOnly ? `仅显示 ${filteredDcaSignalHistory.length} 个变化点` : `显示最近 ${filteredDcaSignalHistory.length} 条扫描`}</p>
                          </div>
                          <Button variant="outline" size="sm" onClick={() => setShowDcaChangesOnly((value) => !value)}>
                            {showDcaChangesOnly ? '显示全部' : '只看变化点'}
                          </Button>
                        </div>
                        {filteredDcaSignalHistory.map((item) => {
                          const metrics = item.metrics || {}
                          const isChangePoint = dcaHistoryChangeIds.has(item.id)
                          return (
                            <div key={item.id} className={`rounded-lg border p-4 ${isChangePoint ? 'border-blue-200 bg-blue-50/40' : ''}`}>
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Badge variant="outline" className={`${getDcaTextClass(item.persisted_light, item.label)} border-current`}>
                                    正式 {formatDcaLight(item.persisted_light)}
                                  </Badge>
                                  {isChangePoint && <Badge variant="outline" className="border-blue-200 bg-blue-50 text-blue-700">变化点</Badge>}
                                  <span className="text-xs text-muted-foreground">信号 {formatDcaLight(item.signal_light)}</span>
                                  {item.candidate_light && (
                                    <span className={`text-xs ${getDcaTextClass(item.candidate_light)}`}>
                                      候选 {formatDcaLight(item.candidate_light)} {item.candidate_confirm_count || 0}/2
                                    </span>
                                  )}
                                </div>
                                <span className="text-xs text-muted-foreground">{formatBeijingTime(item.scanned_at)}</span>
                              </div>
                              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
                                <div className="rounded bg-muted/40 p-2">现价 <span className="font-mono">{item.price?.toFixed(3) || '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">触发价 <span className="font-mono">{item.trigger_price?.toFixed(3) || '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">倍率 <span className="font-mono">{item.budget_multiplier != null ? `${item.budget_multiplier}x` : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">分位 <span className="font-mono">{metrics.valuation_percentile != null ? `${Number(metrics.valuation_percentile).toFixed(1)}%` : '-'}</span></div>
                              </div>
                              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-4">
                                <div className="rounded bg-muted/40 p-2">MA20 <span className="font-mono">{metrics.trend_ma20 != null ? Number(metrics.trend_ma20).toFixed(3) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">MA60 <span className="font-mono">{metrics.trend_ma60 != null ? Number(metrics.trend_ma60).toFixed(3) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">MA120 <span className="font-mono">{metrics.trend_ma120 != null ? Number(metrics.trend_ma120).toFixed(3) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">轨道 <span>{formatDcaTrack(metrics.track)}</span></div>
                              </div>
                              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-4">
                                <div className="rounded bg-muted/40 p-2">MA20斜率 <span className="font-mono">{metrics.trend_ma20_slope_pct != null ? `${Number(metrics.trend_ma20_slope_pct).toFixed(2)}%` : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">ATR14 <span className="font-mono">{metrics.trend_atr14 != null ? Number(metrics.trend_atr14).toFixed(3) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">ATR倍数 <span className="font-mono">{metrics.trend_atr_multiplier != null ? `${Number(metrics.trend_atr_multiplier).toFixed(1)}x` : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">量能 <span className="font-mono">{metrics.trend_volume_ratio != null ? `${Number(metrics.trend_volume_ratio).toFixed(2)}x` : '-'}</span></div>
                              </div>
                              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
                                <div className="rounded bg-muted/40 p-2">评分 <span className="font-mono">{metrics.quality_score != null ? Number(metrics.quality_score).toFixed(1) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">浅绿价 <span className="font-mono">{metrics.green_trigger_price != null ? Number(metrics.green_trigger_price).toFixed(3) : '-'}</span></div>
                                <div className="rounded bg-muted/40 p-2">深绿价 <span className="font-mono">{metrics.deep_green_trigger_price != null ? Number(metrics.deep_green_trigger_price).toFixed(3) : '-'}</span></div>
                              </div>
                              <p className="mt-3 text-xs leading-5 text-muted-foreground">{item.reason || '-'}</p>
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="rounded-lg border py-10 text-center text-muted-foreground">暂无扫描历史</div>
                    )}
                  </TabsContent>
                </Tabs>
              </>
            )}
          </DialogContent>
        </Dialog>

        <Dialog open={showAdviceModal && !!currentAdvice} onOpenChange={setShowAdviceModal}>
          <DialogContent className="flex max-h-[88vh] w-[calc(100vw-2rem)] max-w-4xl flex-col gap-0 overflow-hidden p-0">
            {currentAdvice && (
              <>
                <DialogHeader className="border-b px-6 py-4 text-left">
                  <DialogTitle>投资建议</DialogTitle>
                </DialogHeader>

                <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-lg">{currentAdvice.etf_code}</span>
                      <span className="text-muted-foreground">{currentAdvice.etf_name}</span>
                    </div>

                    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex flex-wrap items-center gap-3">
                        <Badge
                          variant="outline"
                          className={`text-sm ${getAdviceTypeColor(currentAdvice.advice_type)} border-current px-3 py-1`}
                        >
                          {getAdviceTypeLabel(currentAdvice.advice_type)}
                        </Badge>
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">置信度</span>
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
                              <div
                                className={`h-full rounded-full transition-all ${
                                  currentAdvice.confidence >= 80
                                    ? 'bg-green-500'
                                    : currentAdvice.confidence >= 60
                                      ? 'bg-blue-500'
                                      : currentAdvice.confidence >= 40
                                        ? 'bg-yellow-500'
                                        : 'bg-red-500'
                                }`}
                                style={{ width: `${currentAdvice.confidence}%` }}
                              />
                            </div>
                            <span className="text-sm font-semibold">{currentAdvice.confidence.toFixed(0)}%</span>
                          </div>
                        </div>
                      </div>
                      <Button size="sm" variant="outline" onClick={handleRegenerateAdvice}>
                        <RefreshCw className="mr-1 h-3.5 w-3.5" />
                        重新分析
                      </Button>
                    </div>

                    <div>
                      <h4 className="mb-2 text-sm font-medium text-muted-foreground">多周期建议</h4>
                      <div className="space-y-3">
                        <div className="rounded-xl border bg-primary/5 p-4">
                          <div className="text-xs font-medium text-muted-foreground">主建议</div>
                          <p className="mt-2 text-sm leading-relaxed">
                            {currentAdvice.main_judgment || `中期以${getAdviceTypeLabel(currentAdvice.advice_type)}为主，${currentAdvice.medium_term.conclusion}`}
                          </p>
                          {currentAdvice.summary && (
                            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                              {currentAdvice.summary}
                            </p>
                          )}
                          {(currentAdvice.why.length > 0 || currentAdvice.news_basis.length > 0 || currentAdvice.policy_basis.length > 0) && (
                            <div className="mt-3 flex flex-wrap gap-2">
                              {currentAdvice.why.slice(0, 3).map((item, index) => (
                                <span key={`why-${index}`} className="rounded-full border bg-white/70 px-2 py-0.5 text-xs text-foreground/70">
                                  {item}
                                </span>
                              ))}
                              {currentAdvice.news_basis[0] && (
                                <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-800">
                                  新闻：{currentAdvice.news_basis[0]}
                                </span>
                              )}
                              {currentAdvice.policy_basis[0] && (
                                <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs text-violet-800">
                                  政策：{currentAdvice.policy_basis[0]}
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        <AdviceEventContextPanel eventContext={currentAdvice.event_context} />

                        <div className="rounded-xl border bg-background/60 p-4">
                          <div className="text-xs font-medium text-muted-foreground">补充判断</div>
                          <div className="mt-2 space-y-3 text-sm">
                            <div>
                              <span className="font-medium">短期：</span>
                              <span>{currentAdvice.short_term.action}，{currentAdvice.short_term.conclusion}</span>
                              {(currentAdvice.short_term.signals[0] || currentAdvice.short_term.risks[0]) && (
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {currentAdvice.short_term.signals[0] ? `依据：${currentAdvice.short_term.signals[0]}` : ''}
                                  {currentAdvice.short_term.signals[0] && currentAdvice.short_term.risks[0] ? '；' : ''}
                                  {currentAdvice.short_term.risks[0] ? `风险：${currentAdvice.short_term.risks[0]}` : ''}
                                </p>
                              )}
                            </div>
                            <div>
                              <span className="font-medium">长期：</span>
                              <span>{currentAdvice.long_term.action}，{currentAdvice.long_term.conclusion}</span>
                              {(currentAdvice.long_term.signals[0] || currentAdvice.long_term.risks[0]) && (
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {currentAdvice.long_term.signals[0] ? `依据：${currentAdvice.long_term.signals[0]}` : ''}
                                  {currentAdvice.long_term.signals[0] && currentAdvice.long_term.risks[0] ? '；' : ''}
                                  {currentAdvice.long_term.risks[0] ? `风险：${currentAdvice.long_term.risks[0]}` : ''}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {currentAdvice.current_price && (
                      <div className="text-sm text-muted-foreground">
                        当前价格: {currentAdvice.current_price.toFixed(3)} | 盈亏: {currentAdvice.pnl_pct?.toFixed(2)}%
                      </div>
                    )}

                    <div className="flex items-center gap-1.5 border-t pt-2 text-xs text-muted-foreground">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      <span>
                        决策时间: {formatBeijingTime(currentAdvice.created_at, {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end border-t px-6 py-4">
                  <Button onClick={() => setShowAdviceModal(false)}>关闭</Button>
                </div>
              </>
            )}
          </DialogContent>
        </Dialog>

        {/* ETF详情弹窗 */}
        {detailPortfolio && (
          <EtfDetailModal
            portfolio={detailPortfolio}
            onClose={() => setDetailPortfolio(null)}
          />
        )}

        <ConfirmDialog
          open={!!deleteTarget}
          onOpenChange={(open) => {
            if (!open && !deleting) {
              setDeleteTarget(null)
            }
          }}
          title="删除持仓"
          description={deleteTarget ? `确认删除 ${deleteTarget.etf_name || deleteTarget.etf_code} 持仓记录吗？此操作不可撤销。` : ''}
          confirmText="确认删除"
          onConfirm={handleDelete}
          loading={deleting}
          variant="destructive"
        />
      </CardContent>
    </Card>
  )
}

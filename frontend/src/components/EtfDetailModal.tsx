import { type IndicatorLineKey, type BenchmarkKey, type RuleCheck, type CandlePoint, buildTradeSignal, isCurrentShanghaiIntradayPoint, CandlestickChart } from "./market/EtfChart"
import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X, BarChart3, Activity, Calendar, Lightbulb, Loader2, RefreshCw, Clock, Database, Maximize2, Minimize2 } from 'lucide-react'
import {
  marketApi, adviceApi,
  type PortfolioWithMarket, type MarketHistoryResponse, type AdviceResponse, type AdviceLogResponse, type EtfProfileResponse
} from '@/services/api'
import { AdviceEventContextPanel, parseEventContextFromReason } from '@/components/AdviceEventContextPanel'
import { formatBeijingTime } from '@/utils/time'

interface EtfDetailModalProps {
  portfolio: PortfolioWithMarket
  onClose: () => void
}

const adviceTypeConfig: Record<string, { label: string; color: string; bgColor: string }> = {
  buy: { label: '买入', color: 'text-red-600', bgColor: 'bg-red-50' },
  sell: { label: '卖出', color: 'text-green-600', bgColor: 'bg-green-50' },
  hold: { label: '持有', color: 'text-blue-600', bgColor: 'bg-blue-50' },
  add: { label: '加仓', color: 'text-orange-600', bgColor: 'bg-orange-50' },
  reduce: { label: '减仓', color: 'text-yellow-600', bgColor: 'bg-yellow-50' },
}

type ParsedPeriodAdvice = {
  label: string
  adviceType: string
  action: string
  confidence: number
  conclusion: string
  signals: string[]
  risks: string[]
}

type ParsedDecisionSummary = {
  mainJudgment: string
  action: string
  why: string[]
  newsBasis: string[]
  policyBasis: string[]
}

type HistoryRangeDays = 60 | 120 | 365
type ChartRangeKey = 'today' | HistoryRangeDays
function splitAdviceItems(value: string) {
  return value
    .split(/[；;]\s*/)
    .map((item) => item.trim())
    .filter((item) => item && item !== '暂无' && item !== '-')
}

function parseMultiHorizonReason(reason: string | null): ParsedPeriodAdvice[] {
  const text = reason || ''
  const sections = text
    .split(/(?=【(?:短期|中期|长期)】)/)
    .map((item) => item.trim())
    .filter(Boolean)

  return sections
    .map((section) => {
      const lines = section.split('\n').map((item) => item.trim()).filter(Boolean)
      const header = lines[0] || ''
      const match = header.match(/^【(短期|中期|长期)】([^（(]+)(?:[（(](\d+)%[）)])?/)
      return {
        label: match?.[1] || '周期',
        adviceType: (match?.[2] || 'hold').trim().toLowerCase(),
        action: lines.find((line) => line.startsWith('动作：'))?.replace('动作：', '').trim() || '继续观察',
        confidence: Number(match?.[3] || 0),
        conclusion: lines.find((line) => line.startsWith('结论：'))?.replace('结论：', '').trim() || '',
        signals: splitAdviceItems(lines.find((line) => line.startsWith('信号：'))?.replace('信号：', '').trim() || ''),
        risks: splitAdviceItems(lines.find((line) => line.startsWith('风险：'))?.replace('风险：', '').trim() || ''),
      }
    })
    .filter((item) => item.conclusion || item.signals.length > 0 || item.risks.length > 0)
}

function parseDecisionSummary(reason: string | null): ParsedDecisionSummary | null {
  const text = reason || ''
  if (!text.includes('主判断：') && !text.includes('执行动作：') && !text.includes('关键依据：')) {
    return null
  }

  const lines = text.split('\n').map((item) => item.trim()).filter(Boolean)
  return {
    mainJudgment: lines.find((line) => line.startsWith('主判断：'))?.replace('主判断：', '').trim() || '',
    action: lines.find((line) => line.startsWith('执行动作：'))?.replace('执行动作：', '').trim() || '',
    why: splitAdviceItems(lines.find((line) => line.startsWith('关键依据：'))?.replace('关键依据：', '').trim() || ''),
    newsBasis: splitAdviceItems(lines.find((line) => line.startsWith('新闻依据：'))?.replace('新闻依据：', '').trim() || ''),
    policyBasis: splitAdviceItems(lines.find((line) => line.startsWith('政策依据：'))?.replace('政策依据：', '').trim() || ''),
  }
}

function LegacyAdviceContent({ reason }: { reason: string | null }) {
  const periods = parseMultiHorizonReason(reason)
  const summary = parseDecisionSummary(reason)
  const eventContext = parseEventContextFromReason(reason)
  if (periods.length > 0) {
    const medium = periods.find((period) => period.label === '中期')
    const short = periods.find((period) => period.label === '短期')
    const long = periods.find((period) => period.label === '长期')
    return (
      <div className="space-y-3">
        <div className="rounded-xl border bg-primary/5 p-4">
          <div className="text-xs font-medium text-muted-foreground">主建议</div>
          <p className="mt-2 text-sm leading-relaxed">
            {summary?.mainJudgment || `中期以${adviceTypeConfig[medium?.adviceType || 'hold'].label}为主，${medium?.conclusion || '延续中期判断'}`}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            执行动作：{summary?.action || medium?.adviceType || 'hold'}。短期偏{short?.conclusion || '短线节奏'}；长期看{long?.conclusion || '长期配置价值'}
          </p>
        </div>
        {(summary?.why.length || summary?.newsBasis.length || summary?.policyBasis.length) ? (
          <div className="rounded-xl border bg-background/60 p-4">
            <div className="text-xs font-medium text-muted-foreground">依据摘要</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {summary.why.slice(0, 3).map((item, index) => (
                <span key={`legacy-why-${index}`} className="rounded-full border bg-white/70 px-2 py-0.5 text-xs text-foreground/70">
                  {item}
                </span>
              ))}
              {summary.newsBasis[0] && (
                <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-800">
                  新闻：{summary.newsBasis[0]}
                </span>
              )}
              {summary.policyBasis[0] && (
                <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs text-violet-800">
                  政策：{summary.policyBasis[0]}
                </span>
              )}
            </div>
          </div>
        ) : null}
        <AdviceEventContextPanel eventContext={eventContext} compact />
        <div className="rounded-xl border bg-background/60 p-4">
          <div className="text-xs font-medium text-muted-foreground">补充判断</div>
          <div className="mt-2 space-y-3 text-sm">
            <div>
              <span className="font-medium">短期：</span>
              <span>{short?.action || '继续观察'}，{short?.conclusion || '短线节奏待确认'}</span>
              {(short?.signals[0] || short?.risks[0]) && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {short?.signals[0] ? `依据：${short.signals[0]}` : ''}
                  {short?.signals[0] && short?.risks[0] ? '；' : ''}
                  {short?.risks[0] ? `风险：${short.risks[0]}` : ''}
                </p>
              )}
            </div>
            <div>
              <span className="font-medium">长期：</span>
              <span>{long?.action || '继续持有'}，{long?.conclusion || '长期配置价值待观察'}</span>
              {(long?.signals[0] || long?.risks[0]) && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {long?.signals[0] ? `依据：${long.signals[0]}` : ''}
                  {long?.signals[0] && long?.risks[0] ? '；' : ''}
                  {long?.risks[0] ? `风险：${long.risks[0]}` : ''}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const lines = (reason || '').split('\n').map((line) => line.trim()).filter(Boolean)
  return (
    <div className="rounded-lg border bg-background/70 p-4"> 
      <div className="space-y-2 text-sm leading-relaxed text-foreground/80"> 
        {lines.length > 0 ? lines.map((line, index) => <p key={`${line}-${index}`}>{line}</p>) : <p>-</p>}
      </div>
    </div>
  )
}

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : '-'
  return String(value)
}

function pickValue(row: Record<string, unknown>, names: string[]) {
  for (const name of names) {
    if (row[name] !== undefined && row[name] !== null && row[name] !== '') return row[name]
  }
  return undefined
}

function visibleProfileErrors(errors: string[]) {
  return errors.filter((item) => {
    return !item.includes('fund_individual_basic_info_xq') && !item.includes('fund_portfolio_bond_hold_em')
  })
}

export function EtfDetailModal({ portfolio: p, onClose }: EtfDetailModalProps) {
  const [activeTab, setActiveTab] = useState<'chart' | 'advice' | 'profile'>('chart')
  const supportsIntraday = !['otc_fund', 'cash', 'money_fund'].includes(p.asset_type)
  const isVirtualPortfolio = p.id < 0
  const [activeChartRange, setActiveChartRange] = useState<ChartRangeKey>(supportsIntraday ? 'today' : 60)
  const [historyDays, setHistoryDays] = useState<HistoryRangeDays>(60)
  const [chartFullscreen, setChartFullscreen] = useState(false)
  const [visibleIndicators, setVisibleIndicators] = useState<Record<IndicatorLineKey, boolean>>({
    ma5: true,
    ma10: true,
    ma20: true,
    ma60: false,
    boll: false,
    macd: false,
  })
  const [intradayIndicators, setIntradayIndicators] = useState<Record<IndicatorLineKey, boolean>>({
    ma5: true,
    ma10: false,
    ma20: true,
    ma60: false,
    boll: false,
    macd: true,
  })
  const [historyData, setHistoryData] = useState<MarketHistoryResponse | null>(null)
  const [intradayData, setIntradayData] = useState<MarketHistoryResponse | null>(null)
  const [benchmarkHistory, setBenchmarkHistory] = useState<Record<BenchmarkKey, MarketHistoryResponse | null>>({ hs300: null, csiA500: null })
  const [historyLoading, setHistoryLoading] = useState(true)
  const [intradayLoading, setIntradayLoading] = useState(true)
  const [profile, setProfile] = useState<EtfProfileResponse | null>(null)
  const [profileLoading, setProfileLoading] = useState(true)
  const [advice, setAdvice] = useState<AdviceResponse | null>(null)
  const [adviceLoading, setAdviceLoading] = useState(false)
  const [latestAdvice, setLatestAdvice] = useState<AdviceLogResponse | null>(null)
  const [latestLoading, setLatestLoading] = useState(true)

  useEffect(() => {
    setActiveChartRange(supportsIntraday ? 'today' : 60)
  }, [p.etf_code, supportsIntraday])

  useEffect(() => {
    fetchHistory()
  }, [p.etf_code, historyDays])

  useEffect(() => {
    if (supportsIntraday) fetchIntraday()
    else setIntradayData(null)
  }, [p.etf_code, supportsIntraday])

  useEffect(() => {
    fetchBenchmarkHistory()
  }, [historyDays])

  useEffect(() => {
    fetchProfile()
    fetchLatestAdvice()
  }, [p.etf_code])

  const fetchLatestAdvice = async () => {
    setLatestLoading(true)
    try {
      const res = await adviceApi.getLatest()
      const data = res.data || {}
      setLatestAdvice(data[p.etf_code] || null)
    } catch (e) {
      console.error('Failed to fetch latest advice:', e)
    } finally {
      setLatestLoading(false)
    }
  }

  const fetchHistory = async () => {
    setHistoryLoading(true)
    try {
      const res = await marketApi.getHistory(p.etf_code, historyDays)
      setHistoryData(res.data)
    } catch (e) {
      console.error('Failed to fetch history:', e)
    } finally {
      setHistoryLoading(false)
    }
  }

  const fetchIntraday = async () => {
    setIntradayLoading(true)
    try {
      const res = await marketApi.getIntraday(p.etf_code, '1m', 240)
      setIntradayData(res.data)
    } catch (e) {
      console.error('Failed to fetch intraday history:', e)
      setIntradayData(null)
    } finally {
      setIntradayLoading(false)
    }
  }

  const fetchBenchmarkHistory = async () => {
    try {
      const [hs300Res, csiA500Res] = await Promise.allSettled([
        marketApi.getHistory('000300', historyDays),
        marketApi.getHistory('000510', historyDays),
      ])
      setBenchmarkHistory({
        hs300: hs300Res.status === 'fulfilled' ? hs300Res.value.data : null,
        csiA500: csiA500Res.status === 'fulfilled' ? csiA500Res.value.data : null,
      })
    } catch (e) {
      console.error('Failed to fetch benchmark history:', e)
      setBenchmarkHistory({ hs300: null, csiA500: null })
    }
  }

  const fetchProfile = async (forceRefresh = false) => {
    setProfileLoading(true)
    try {
      const res = await marketApi.getEtfProfile(p.etf_code, undefined, forceRefresh)
      setProfile(res.data)
    } catch (e) {
      console.error('Failed to fetch ETF profile:', e)
      setProfile(null)
    } finally {
      setProfileLoading(false)
    }
  }

  const fetchAdvice = async () => {
    setAdviceLoading(true)
    try {
      const res = isVirtualPortfolio
        ? await adviceApi.generateForSymbol({ code: p.etf_code, name: p.etf_name, asset_type: p.asset_type })
        : await adviceApi.generateForPortfolio(p.id)
      setAdvice(res.data)
      // 刷新最新建议
      fetchLatestAdvice()
    } catch (e: any) {
      const msg = e?.code === 'ECONNABORTED'
        ? '请求超时，AI正在搜索最新信息，请稍后重试'
        : (e?.response?.data?.detail || '获取建议失败')
      alert(msg)
    } finally {
      setAdviceLoading(false)
    }
  }

  const indicators = historyData?.indicators
  const klines = historyData?.data || []
  const intradayKlines = (intradayData?.data || []).filter(isCurrentShanghaiIntradayPoint)

  const toChartPoint = (k: typeof klines[number], mode: 'daily' | 'intraday'): CandlePoint => {
    const timeLabel = k.trade_time
      ? new Date(k.trade_time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' })
      : k.trade_date.slice(5)
    return {
      date: mode === 'intraday' ? timeLabel : k.trade_date.slice(5),
      fullDate: k.trade_time || k.trade_date,
      provisional: k.provisional || false,
      open: k.open_price,
      close: k.close_price,
      high: k.high_price,
      low: k.low_price,
      volume: k.volume,
      amount: k.amount ?? null,
      change: k.change_pct,
    }
  }

  // K线图数据
  const chartData = klines.map((k) => toChartPoint(k, 'daily'))
  const intradayChartData = intradayKlines.map((k) => toChartPoint(k, 'intraday'))
  const latestClose = chartData.at(-1)?.close ?? null
  const calculateBias = (ma: number | null | undefined) => {
    if (latestClose == null || ma == null || ma <= 0) return null
    return ((latestClose - ma) / ma) * 100
  }
  const biasIndicators = indicators ? {
    bias5: calculateBias(indicators.ma5),
    bias10: calculateBias(indicators.ma10),
    bias20: calculateBias(indicators.ma20),
  } : null
  const formatBias = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return 'N/A'
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  }
  const biasClassName = (value: number | null | undefined) => {
    if (value == null) return ''
    return value >= 0 ? 'text-red-500' : 'text-green-500'
  }
  const confirmedChartData = chartData.filter((item) => !item.provisional)
  const tradeSignal = buildTradeSignal(confirmedChartData, benchmarkHistory)
  const renderRuleCheck = (check: RuleCheck) => (
    <div key={check.label} className="rounded-md border bg-background/70 px-2.5 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium leading-5">{check.label}</div>
        <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-4 ${check.passed == null ? 'bg-slate-100 text-slate-600' : check.passed ? 'bg-red-50 text-red-700' : 'bg-slate-100 text-slate-500'}`}>
          {check.passed == null ? '待数据' : check.passed ? '满足' : '未满足'}
        </span>
      </div>
      <div className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{check.detail}</div>
    </div>
  )

  const displayAdvice = advice || latestAdvice
  const profileErrors = profile ? visibleProfileErrors(profile.errors || []) : []
  const displayConfig = displayAdvice ? (adviceTypeConfig[displayAdvice.advice_type || 'hold'] || adviceTypeConfig.hold) : null
  const displayConfidence = displayAdvice ? (displayAdvice.confidence || 0) : 0
  const displayTime = displayAdvice?.created_at || null
  const indicatorOptions: Array<{ key: IndicatorLineKey; label: string; intradayLabel?: string; colorClassName: string; intradayHidden?: boolean }> = [
    { key: 'ma5', label: 'MA5', intradayLabel: 'MA5m', colorClassName: 'bg-blue-600' },
    { key: 'ma10', label: 'MA10', intradayLabel: 'MA10m', colorClassName: 'bg-purple-600' },
    { key: 'ma20', label: 'MA20', intradayLabel: 'MA20m', colorClassName: 'bg-orange-500' },
    { key: 'ma60', label: 'MA60', intradayLabel: 'MA60m', colorClassName: 'bg-slate-600' },
    { key: 'boll', label: 'BOLL', colorClassName: 'bg-sky-500', intradayHidden: true },
    { key: 'macd', label: 'MACD', colorClassName: 'bg-cyan-600' },
  ]
  const toggleIndicator = (key: IndicatorLineKey) => {
    setVisibleIndicators((prev) => ({ ...prev, [key]: !prev[key] }))
  }
  const toggleIntradayIndicator = (key: IndicatorLineKey) => {
    setIntradayIndicators((prev) => ({ ...prev, [key]: !prev[key] }))
  }
  const latestIntradayTime = intradayChartData.at(-1)?.date || null
  const intradayPointCount = intradayChartData.length
  const latestDailyDate = historyData?.latest_trade_date || chartData.at(-1)?.fullDate?.slice(0, 10) || null
  const hasProvisionalDailyPoint = historyData?.has_provisional || chartData.some((item) => item.provisional)
  const quoteTimeLabel = p.market_refreshed_at ? formatBeijingTime(p.market_refreshed_at) : null
  const activeChartData = activeChartRange === 'today' ? intradayChartData : chartData
  const activeChartLoading = activeChartRange === 'today' ? intradayLoading : historyLoading
  const activeChartIndicators = activeChartRange === 'today' ? intradayIndicators : visibleIndicators
  const activeToggleIndicator = activeChartRange === 'today' ? toggleIntradayIndicator : toggleIndicator
  const activeChartEmptyText = activeChartRange === 'today' ? '今日分钟线暂不可用，可刷新或切换周期' : '暂无K线数据'
  const historyRangeOptions: Array<{ key: ChartRangeKey; days?: HistoryRangeDays; label: string; title: string }> = [
    ...(supportsIntraday ? [{ key: 'today' as const, label: '今日', title: '今日实时趋势' }] : []),
    { key: 60, days: 60, label: '60日', title: '60日趋势' },
    { key: 120, days: 120, label: '120日', title: '120日趋势' },
    { key: 365, days: 365, label: '1年', title: '1年趋势' },
  ]
  const activeHistoryRange = historyRangeOptions.find((option) => option.key === activeChartRange) || historyRangeOptions[supportsIntraday ? 0 : 0]
  const selectChartRange = (option: typeof historyRangeOptions[number]) => {
    setActiveChartRange(option.key)
    if (option.days) setHistoryDays(option.days)
  }
  const refreshActiveChart = () => {
    if (activeChartRange === 'today') fetchIntraday()
    else fetchHistory()
  }

  const renderIndicatorToggles = (
    values: Record<IndicatorLineKey, boolean>,
    onToggle: (key: IndicatorLineKey) => void,
  ) => (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1.5 text-xs text-muted-foreground">
      {indicatorOptions.filter((option) => !(activeChartRange === 'today' && option.intradayHidden)).map((option) => (
        <label key={option.key} className="inline-flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={values[option.key]}
            onChange={() => onToggle(option.key)}
            className="h-3.5 w-3.5 rounded border-muted-foreground/40 accent-primary"
          />
          <span className={`h-0.5 w-4 ${option.colorClassName}`} />
          <span>{activeChartRange === 'today' ? (option.intradayLabel || option.label) : option.label}</span>
        </label>
      ))}
    </div>
  )
  const renderChartControls = (variant: 'compact' | 'fullscreen' = 'compact') => (
    <div className="flex min-w-0 flex-wrap items-center gap-3">
      <div className="inline-flex shrink-0 rounded-md border bg-background p-0.5 text-xs">
        {historyRangeOptions.map((option) => (
          <button
            key={option.key}
            type="button"
            onClick={() => selectChartRange(option)}
            className={`h-7 px-2.5 font-medium transition-colors ${activeChartRange === option.key ? 'rounded bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {option.label}
          </button>
        ))}
      </div>
      {renderIndicatorToggles(activeChartIndicators, activeToggleIndicator)}
      <div className="flex shrink-0 items-center gap-2">
        <Button size="sm" variant="ghost" onClick={refreshActiveChart} disabled={activeChartLoading} className="h-8 px-2.5 text-xs">
          <RefreshCw className={`h-3.5 w-3.5 mr-1 ${activeChartLoading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
        {variant === 'compact' ? (
          <Button size="sm" variant="outline" onClick={() => setChartFullscreen(true)} className="h-8 px-2.5 text-xs">
            <Maximize2 className="h-3.5 w-3.5 mr-1" />
            全屏
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setChartFullscreen(false)} className="h-8 px-2.5 text-xs">
            <Minimize2 className="h-3.5 w-3.5 mr-1" />
            退出
          </Button>
        )}
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      {chartFullscreen ? (
        <div className="fixed inset-0 z-[60] bg-background p-4" onClick={(event) => event.stopPropagation()}>
          <div className="flex h-full flex-col gap-4">
            <div className="space-y-3 border-b pb-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-lg font-bold">{p.etf_code}</span>
                  <span className="text-sm text-muted-foreground">{p.etf_name || '-'}</span>
                </div>
                <h3 className="mt-1 text-base font-semibold">{activeHistoryRange.title}</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {p.asset_type === 'otc_fund' ? '最新净值' : '当前价'} {p.current_price?.toFixed(3) || '-'}
                  {p.change_pct != null ? ` / ${p.change_pct >= 0 ? '+' : ''}${p.change_pct.toFixed(2)}%` : ''}
                  {quoteTimeLabel ? ` / ${p.asset_type === 'otc_fund' ? '净值更新' : '实时'} ${quoteTimeLabel}` : ''}
                </p>
              </div>
              <div>{renderChartControls('fullscreen')}</div>
            </div>
            <div className="min-h-0 flex-1">
              {activeChartLoading ? (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin mr-2" />
                  加载中...
                </div>
              ) : activeChartData.length > 0 ? (
                <CandlestickChart
                  data={activeChartData}
                  costPrice={activeChartRange === 'today' ? null : p.cost_price}
                  visibleIndicators={activeChartIndicators}
                  className="h-full"
                  partialMovingAverage={false}
                  timeframe={activeChartRange === 'today' ? 'intraday' : 'daily'}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  {activeChartEmptyText}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
      <div
        className="bg-background rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* 顶部标题 */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div className="flex items-center gap-3">
            <span className="font-mono text-xl font-bold">{p.etf_code}</span>
            <span className="text-lg text-muted-foreground">{p.etf_name || '-'}</span>
            <span className={`text-lg font-semibold ${(p.change_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
              {p.current_price?.toFixed(3) || '-'}
              {p.change_pct != null && (
                <span className="text-sm ml-1">
                  {p.change_pct >= 0 ? '+' : ''}{p.change_pct.toFixed(2)}%
                </span>
              )}
            </span>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        {/* 持仓状态 */}
        <div className="px-6 py-3 bg-muted/30 border-b">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">份额</span>
              <p className="font-semibold">{p.shares.toLocaleString()}</p>
            </div>
            <div>
              <span className="text-muted-foreground">成本价</span>
              <p className="font-semibold">{p.cost_price.toFixed(4)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">市值</span>
              <p className="font-semibold">{p.market_value?.toFixed(2) || '-'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">盈亏</span>
              <p className={`font-semibold ${(p.pnl || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                {p.pnl != null ? `${p.pnl >= 0 ? '+' : ''}${p.pnl.toFixed(2)}` : '-'}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">收益率</span>
              <p className={`font-semibold ${(p.pnl_pct || 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                {p.pnl_pct != null ? `${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct.toFixed(2)}%` : '-'}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">持仓天数</span>
              <p className="font-semibold">{p.holding_days != null ? `${p.holding_days}天` : '-'}</p>
            </div>
          </div>
        </div>

        {/* Tab 切换 */}
        <div className="flex border-b px-6">
          <button
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === 'chart' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setActiveTab('chart')}
          >
            <BarChart3 className="h-4 w-4 inline mr-1.5" />
            行情走势
          </button>
          <button
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === 'advice' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setActiveTab('advice')}
          >
            <Lightbulb className="h-4 w-4 inline mr-1.5" />
            AI决策
          </button>
          <button
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === 'profile' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
            onClick={() => setActiveTab('profile')}
          >
            <Database className="h-4 w-4 inline mr-1.5" />
            资料
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {activeTab === 'chart' && (
            <>
              {/* K线图 */}
              <Card>
                <CardContent className="pt-4">
                  <div className="mb-3 space-y-3">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                      <h3 className="text-sm font-semibold">行情趋势</h3>
                      {activeChartRange === 'today' ? (
                        <span className="text-xs text-muted-foreground">分钟K：{intradayPointCount}根 · 最新分钟：{latestIntradayTime || '暂无更新'}{quoteTimeLabel ? ` · 实时 ${quoteTimeLabel}` : ''}</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">日K最新：{latestDailyDate || '暂无'}{hasProvisionalDailyPoint ? ' · 含盘中估算' : ''}{quoteTimeLabel ? ` · 实时 ${quoteTimeLabel}` : ''}</span>
                      )}
                    </div>
                    <div>{renderChartControls()}</div>
                  </div>
                  {activeChartLoading ? (
                    <div className="h-64 flex items-center justify-center text-muted-foreground">
                      <Loader2 className="h-6 w-6 animate-spin mr-2" />
                      加载中...
                    </div>
                  ) : activeChartData.length > 0 ? (
                    <CandlestickChart data={activeChartData} costPrice={activeChartRange === 'today' ? null : p.cost_price} visibleIndicators={activeChartIndicators} partialMovingAverage={false} timeframe={activeChartRange === 'today' ? 'intraday' : 'daily'} />
                  ) : (
                    <div className="h-64 flex items-center justify-center text-muted-foreground">
                      {activeChartEmptyText}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* 技术指标 */}
              <Card>
                <CardContent className="pt-4">
                  <h3 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                    <Activity className="h-4 w-4" />
                    日线技术指标
                    <Badge variant="outline" className="ml-1.5 align-middle text-[10px]">基于日线，不随今日分钟图变化</Badge>
                  </h3>
                  {indicators ? (
                    <div className="space-y-4">
                      <div className={`rounded-xl border p-3.5 ${tradeSignal.toneClassName}`}>
                        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <div className="text-xs font-medium opacity-80">日线规则信号</div>
                            <div className="mt-1 text-lg font-semibold">{tradeSignal.label}</div>
                            <p className="mt-1 text-xs leading-5">{tradeSignal.summary}</p>
                          </div>
                          <Badge variant="outline" className="border-current bg-background/70">
                            日线规则
                          </Badge>
                        </div>
                        <div className="mt-3 grid gap-2.5 lg:grid-cols-2">
                          <div>
                            <div className="mb-1.5 text-[11px] font-semibold opacity-80">买入条件</div>
                            <div className="grid gap-1.5">{tradeSignal.buyChecks.map(renderRuleCheck)}</div>
                          </div>
                          <div>
                            <div className="mb-1.5 text-[11px] font-semibold opacity-80">卖出条件</div>
                            <div className="grid gap-1.5">{tradeSignal.sellChecks.map(renderRuleCheck)}</div>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MA5</span>
                        <p className="font-mono font-semibold">{indicators.ma5?.toFixed(3) ?? 'N/A'}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MA10</span>
                        <p className="font-mono font-semibold">{indicators.ma10?.toFixed(3) ?? 'N/A'}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MA20</span>
                        <p className="font-mono font-semibold">{indicators.ma20?.toFixed(3) ?? 'N/A'}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">BIAS5</span>
                        <p className={`font-mono font-semibold ${biasClassName(biasIndicators?.bias5)}`}>
                          {formatBias(biasIndicators?.bias5)}
                        </p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">BIAS10</span>
                        <p className={`font-mono font-semibold ${biasClassName(biasIndicators?.bias10)}`}>
                          {formatBias(biasIndicators?.bias10)}
                        </p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">BIAS20</span>
                        <p className={`font-mono font-semibold ${biasClassName(biasIndicators?.bias20)}`}>
                          {formatBias(biasIndicators?.bias20)}
                        </p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">RSI(14)</span>
                        <p className={`font-mono font-semibold ${indicators.rsi14 != null ? (indicators.rsi14 > 70 ? 'text-red-500' : indicators.rsi14 < 30 ? 'text-green-500' : '') : ''}`}>
                          {indicators.rsi14?.toFixed(2) ?? 'N/A'}
                        </p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MACD DIF</span>
                        <p className="font-mono font-semibold">{indicators.macd_dif?.toFixed(4) ?? 'N/A'}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MACD DEA</span>
                        <p className="font-mono font-semibold">{indicators.macd_dea?.toFixed(4) ?? 'N/A'}</p>
                      </div>
                      <div className="space-y-1">
                        <span className="text-muted-foreground">MACD柱</span>
                        <p className={`font-mono font-semibold ${indicators.macd_histogram != null ? (indicators.macd_histogram > 0 ? 'text-red-500' : 'text-green-500') : ''}`}>
                          {indicators.macd_histogram?.toFixed(4) ?? 'N/A'}
                        </p>
                      </div>
                      </div>
                    </div>
                  ) : (
                    <p className="text-muted-foreground text-sm">暂无技术指标数据</p>
                  )}
                </CardContent>
              </Card>

              {/* 近期行情表格 */}
              <Card>
                <CardContent className="pt-4">
                  <h3 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                    <Calendar className="h-4 w-4" />
                    近期行情
                  </h3>
                  {klines.length > 0 ? (
                    <div className="overflow-x-auto max-h-48 overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-background">
                          <tr className="border-b text-muted-foreground">
                            <th className="text-left py-1.5 px-2">日期</th>
                            <th className="text-right py-1.5 px-2">开盘</th>
                            <th className="text-right py-1.5 px-2">收盘</th>
                            <th className="text-right py-1.5 px-2">最高</th>
                            <th className="text-right py-1.5 px-2">最低</th>
                            <th className="text-right py-1.5 px-2">涨跌</th>
                            <th className="text-right py-1.5 px-2">成交量</th>
                          </tr>
                        </thead>
                        <tbody>
                          {[...klines].reverse().slice(0, 10).map(k => (
                            <tr key={k.trade_date} className="border-b hover:bg-muted/30">
                              <td className="py-1.5 px-2 font-mono">{k.trade_date}</td>
                              <td className="py-1.5 px-2 text-right">{k.open_price.toFixed(3)}</td>
                              <td className="py-1.5 px-2 text-right font-medium">{k.close_price.toFixed(3)}</td>
                              <td className="py-1.5 px-2 text-right">{k.high_price.toFixed(3)}</td>
                              <td className="py-1.5 px-2 text-right">{k.low_price.toFixed(3)}</td>
                              <td className={`py-1.5 px-2 text-right ${k.change_pct >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                                {k.change_pct >= 0 ? '+' : ''}{k.change_pct.toFixed(2)}%
                              </td>
                              <td className="py-1.5 px-2 text-right">{(k.volume / 10000).toFixed(0)}万</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-muted-foreground text-sm">暂无行情数据</p>
                  )}
                </CardContent>
              </Card>
            </>
          )}

          {activeTab === 'advice' && (
            <div className="space-y-4">
              {adviceLoading && (
                <div className="text-center py-12">
                  <Loader2 className="h-8 w-8 mx-auto animate-spin text-primary mb-4" />
                  <p className="text-muted-foreground">AI正在分析中，请稍候...</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">可能需要搜索最新信息，请耐心等待</p>
                </div>
              )}
              {!adviceLoading && displayAdvice && (
                <Card className={`border-2 ${displayConfig?.bgColor || ''}`}>
                  <CardContent className="pt-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <Badge className={`text-base px-3 py-1 ${displayConfig?.color || ''} bg-white border-current`} variant="outline">
                          {displayConfig?.label || displayAdvice.advice_type}
                        </Badge>
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-muted-foreground">置信度</span>
                          <div className="w-24 h-2.5 bg-muted rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${displayConfidence >= 80 ? 'bg-green-500' : displayConfidence >= 60 ? 'bg-blue-500' : displayConfidence >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`}
                              style={{ width: `${displayConfidence}%` }}
                            />
                          </div>
                          <span className="text-sm font-semibold">{displayConfidence.toFixed(0)}%</span>
                        </div>
                      </div>
                      <Button size="sm" variant="outline" onClick={fetchAdvice}>
                        <RefreshCw className="h-3.5 w-3.5 mr-1" />
                        {isVirtualPortfolio ? '重新观察' : '重新分析'}
                      </Button>
                    </div>
                    <div>
                      <h4 className="text-sm font-medium text-muted-foreground mb-2">多周期建议</h4>
                      {'short_term' in displayAdvice ? (
                        <div className="space-y-3">
                          <div className="rounded-xl border bg-primary/5 p-4">
                            <div className="text-xs font-medium text-muted-foreground">主建议</div>
                            <p className="mt-2 text-sm leading-relaxed">
                              {displayAdvice.main_judgment || `中期以${displayConfig?.label || displayAdvice.advice_type}为主，${displayAdvice.medium_term.conclusion}`}
                            </p>
                            {displayAdvice.summary && (
                              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                                {displayAdvice.summary}
                              </p>
                            )}
                            {(displayAdvice.why.length > 0 || displayAdvice.news_basis.length > 0 || displayAdvice.policy_basis.length > 0) && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {displayAdvice.why.slice(0, 3).map((item, index) => (
                                  <span key={`why-${index}`} className="rounded-full border bg-white/70 px-2 py-0.5 text-xs text-foreground/70">
                                    {item}
                                  </span>
                                ))}
                                {displayAdvice.news_basis[0] && (
                                  <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-800">
                                    新闻：{displayAdvice.news_basis[0]}
                                  </span>
                                )}
                          {displayAdvice.policy_basis[0] && (
                            <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs text-violet-800">
                              政策：{displayAdvice.policy_basis[0]}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                    <AdviceEventContextPanel eventContext={displayAdvice.event_context} />
                    <div className="rounded-xl border bg-background/60 p-4">
                      <div className="text-xs font-medium text-muted-foreground">补充判断</div>
                            <div className="mt-2 space-y-3 text-sm">
                              <div>
                                <span className="font-medium">短期：</span>
                                <span>{displayAdvice.short_term.action}，{displayAdvice.short_term.conclusion}</span>
                                {(displayAdvice.short_term.signals[0] || displayAdvice.short_term.risks[0]) && (
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {displayAdvice.short_term.signals[0] ? `依据：${displayAdvice.short_term.signals[0]}` : ''}
                                    {displayAdvice.short_term.signals[0] && displayAdvice.short_term.risks[0] ? '；' : ''}
                                    {displayAdvice.short_term.risks[0] ? `风险：${displayAdvice.short_term.risks[0]}` : ''}
                                  </p>
                                )}
                              </div>
                              <div>
                                <span className="font-medium">长期：</span>
                                <span>{displayAdvice.long_term.action}，{displayAdvice.long_term.conclusion}</span>
                                {(displayAdvice.long_term.signals[0] || displayAdvice.long_term.risks[0]) && (
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    {displayAdvice.long_term.signals[0] ? `依据：${displayAdvice.long_term.signals[0]}` : ''}
                                    {displayAdvice.long_term.signals[0] && displayAdvice.long_term.risks[0] ? '；' : ''}
                                    {displayAdvice.long_term.risks[0] ? `风险：${displayAdvice.long_term.risks[0]}` : ''}
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <LegacyAdviceContent reason={displayAdvice.reason} />
                      )}
                    </div>
                    {/* 决策时间 */}
                    <div className="flex items-center gap-1.5 pt-2 border-t border-border/50">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-xs text-muted-foreground">
                        决策时间: {formatBeijingTime(displayTime)}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              )}
              {!adviceLoading && !displayAdvice && !latestLoading && (
                <div className="text-center py-12">
                  <Lightbulb className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
                  <p className="text-muted-foreground mb-2">暂无决策建议</p>
                  <Button onClick={fetchAdvice} size="lg">
                    <Lightbulb className="h-4 w-4 mr-2" />
                    {isVirtualPortfolio ? '生成AI观察建议' : '生成AI决策建议'}
                  </Button>
                  {isVirtualPortfolio && (
                    <p className="mx-auto mt-3 max-w-md text-xs leading-5 text-muted-foreground">
                      自选品种会按观察口径分析，不包含持仓成本、盈亏和仓位建议。
                    </p>
                  )}
                </div>
              )}
              {latestLoading && !adviceLoading && (
                <div className="text-center py-8">
                  <Loader2 className="h-6 w-6 mx-auto animate-spin text-muted-foreground" />
                </div>
              )}
            </div>
          )}

          {activeTab === 'profile' && (
            <div className="space-y-4">
              {profileLoading ? (
                <div className="text-center py-12">
                  <Loader2 className="h-8 w-8 mx-auto animate-spin text-primary mb-4" />
                  <p className="text-muted-foreground">正在加载资料...</p>
                </div>
              ) : profile ? (
                <>
                  <Card>
                    <CardContent className="pt-4">
                      <div className="mb-3 flex items-center justify-between">
                        <h3 className="text-sm font-semibold">基本信息</h3>
                        <Button size="sm" variant="ghost" onClick={() => fetchProfile(true)}>
                          <RefreshCw className="h-3.5 w-3.5 mr-1" />
                          刷新
                        </Button>
                      </div>
                      {Object.keys(profile.basic || {}).length > 0 ? (
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                          {Object.entries(profile.basic).slice(0, 12).map(([key, value]) => (
                            <div key={key} className="rounded-lg border bg-muted/20 px-3 py-2">
                              <div className="text-xs text-muted-foreground">{key}</div>
                              <div className="mt-1 truncate text-sm font-medium" title={displayValue(value)}>
                                {displayValue(value)}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">暂无基本资料</p>
                      )}
                    </CardContent>
                  </Card>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <Card>
                      <CardContent className="pt-4">
                        <h3 className="mb-3 text-sm font-semibold">资产配置</h3>
                        {profile.asset_allocation.length > 0 ? (
                          <div className="space-y-2">
                            {profile.asset_allocation.slice(0, 8).map((row, index) => (
                              <div key={index} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                                <span className="truncate">{displayValue(pickValue(row, ['资产类型', '项目', '类型', 'name']))}</span>
                                <span className="font-mono">{displayValue(pickValue(row, ['占比', '比例', 'value', '持仓占比']))}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">暂无资产配置数据</p>
                        )}
                      </CardContent>
                    </Card>

                    <Card>
                      <CardContent className="pt-4">
                        <h3 className="mb-3 text-sm font-semibold">大事提醒 / 公告</h3>
                        {profile.events.length > 0 ? (
                          <div className="max-h-56 space-y-2 overflow-y-auto">
                            {profile.events.slice(0, 8).map((row, index) => (
                              <div key={index} className="rounded-lg border px-3 py-2 text-sm">
                                <div className="font-medium">{displayValue(pickValue(row, ['公告标题', '标题', 'title', '公告名称']))}</div>
                                <div className="mt-1 text-xs text-muted-foreground">
                                  {displayValue(pickValue(row, ['公告日期', '日期', 'date', '发布时间']))}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">暂无公告提醒数据</p>
                        )}
                      </CardContent>
                    </Card>
                  </div>

                  <Card>
                    <CardContent className="pt-4">
                      <div className="mb-3 flex items-center justify-between">
                        <h3 className="text-sm font-semibold">基金持仓股票</h3>
                        <Badge variant="outline">{profile.year}</Badge>
                      </div>
                      {profile.stock_holdings.length > 0 ? (
                        <div className="max-h-80 overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 bg-background">
                              <tr className="border-b text-muted-foreground">
                                <th className="px-2 py-2 text-left">股票代码</th>
                                <th className="px-2 py-2 text-left">股票名称</th>
                                <th className="px-2 py-2 text-right">占比</th>
                                <th className="px-2 py-2 text-right">持股数</th>
                                <th className="px-2 py-2 text-right">持仓市值</th>
                                <th className="px-2 py-2 text-left">季度</th>
                              </tr>
                            </thead>
                            <tbody>
                              {profile.stock_holdings.map((row, index) => (
                                <tr key={index} className="border-b hover:bg-muted/30">
                                  <td className="px-2 py-2 font-mono">{displayValue(pickValue(row, ['股票代码', '代码', 'stock_code']))}</td>
                                  <td className="px-2 py-2">{displayValue(pickValue(row, ['股票名称', '名称', 'stock_name']))}</td>
                                  <td className="px-2 py-2 text-right">{displayValue(pickValue(row, ['占净值比例', '持仓占比', '占比']))}</td>
                                  <td className="px-2 py-2 text-right">{displayValue(pickValue(row, ['持股数', '持股数（万股）', '持仓数量']))}</td>
                                  <td className="px-2 py-2 text-right">{displayValue(pickValue(row, ['持仓市值', '持仓市值（万元）', '市值']))}</td>
                                  <td className="px-2 py-2">{displayValue(pickValue(row, ['季度', '报告期', '持仓截止日期']))}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">暂无基金股票持仓数据</p>
                      )}
                      {profileErrors.length > 0 && (
                        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                          部分数据源不可用：{profileErrors.slice(0, 2).join('；')}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </>
              ) : (
                <div className="text-center py-12">
                  <Database className="h-12 w-12 mx-auto text-muted-foreground/50 mb-4" />
                  <p className="text-muted-foreground mb-4">暂无资料</p>
                  <Button onClick={() => fetchProfile(true)}>
                    <RefreshCw className="h-4 w-4 mr-2" />
                    重新加载
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export { buildTradeSignal, buildTradeSignalFromHistory } from "./market/EtfChart"
export type { BenchmarkKey, CandlePoint, RuleCheck, TradeSignal } from "./market/EtfChart"

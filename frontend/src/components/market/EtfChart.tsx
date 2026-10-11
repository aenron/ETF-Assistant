import type { MarketHistoryResponse } from "@/services/api"

export type IndicatorLineKey = 'ma5' | 'ma10' | 'ma20' | 'ma60' | 'boll' | 'macd'
export type BenchmarkKey = 'hs300' | 'csiA500'

export type RuleCheck = {
  label: string
  passed: boolean | null
  detail: string
}

export type TradeSignal = {
  action: 'buy' | 'clear' | 'reduce' | 'take_profit' | 'watch' | 'insufficient'
  label: string
  toneClassName: string
  summary: string
  buyChecks: RuleCheck[]
  sellChecks: RuleCheck[]
}

export type CandlePoint = {
  date: string
  fullDate: string
  provisional?: boolean
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount: number | null
  change: number
}

export function formatAxisValue(value: number) {
  if (!Number.isFinite(value)) {
    return '-'
  }
  return value.toFixed(3)
}

export function formatVolumeLabel(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return '0'
  }
  if (value >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(0)}万`
  }
  return value.toFixed(0)
}

export function formatAmountLabel(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return '0'
  }
  if (value >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(2)}万`
  }
  return value.toFixed(0)
}

export function calculateMovingAverage(data: CandlePoint[], period: number, partial = false) {
  return data.map((_, index) => {
    if (!partial && index < period - 1) return null
    const start = partial ? Math.max(0, index - period + 1) : index - period + 1
    const window = data.slice(start, index + 1)
    if (window.length === 0) return null
    const sum = window.reduce((total, item) => total + item.close, 0)
    return sum / window.length
  })
}

export function calculateBollingerBands(data: CandlePoint[], period = 20, multiplier = 2) {
  const middle = calculateMovingAverage(data, period)
  const upper: Array<number | null> = []
  const lower: Array<number | null> = []

  data.forEach((_, index) => {
    const middleValue = middle[index]
    if (middleValue == null) {
      upper.push(null)
      lower.push(null)
      return
    }

    const window = data.slice(index - period + 1, index + 1)
    const variance = window.reduce((total, item) => total + (item.close - middleValue) ** 2, 0) / period
    const standardDeviation = Math.sqrt(variance)
    upper.push(middleValue + standardDeviation * multiplier)
    lower.push(middleValue - standardDeviation * multiplier)
  })

  return { middle, upper, lower }
}

export function calculateEma(values: number[], period: number) {
  const multiplier = 2 / (period + 1)
  const result: number[] = []

  values.forEach((value, index) => {
    if (index === 0) {
      result.push(value)
      return
    }
    result.push((value - result[index - 1]) * multiplier + result[index - 1])
  })

  return result
}

export function calculateMacd(data: CandlePoint[]) {
  const closes = data.map((item) => item.close)
  const ema12 = calculateEma(closes, 12)
  const ema26 = calculateEma(closes, 26)
  const dif = closes.map((_, index) => ema12[index] - ema26[index])
  const dea = calculateEma(dif, 9)
  const histogram = dif.map((value, index) => (value - dea[index]) * 2)

  return { dif, dea, histogram }
}

export function formatSignedPct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return 'N/A'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function formatSignalNumber(value: number | null | undefined, digits = 3) {
  if (value == null || !Number.isFinite(value)) return 'N/A'
  return value.toFixed(digits)
}

export function average(values: number[]) {
  if (values.length === 0) return null
  return values.reduce((total, value) => total + value, 0) / values.length
}

export function hasLongUpperShadow(candle: CandlePoint) {
  const range = candle.high - candle.low
  if (range <= 0) return false
  const body = Math.abs(candle.close - candle.open)
  const upperShadow = candle.high - Math.max(candle.open, candle.close)
  return upperShadow / range >= 0.4 && upperShadow >= Math.max(body * 1.5, range * 0.25)
}

export function buildTradeSignal(
  data: CandlePoint[],
  benchmarks: Record<BenchmarkKey, MarketHistoryResponse | null>,
): TradeSignal {
  const ma5Values = calculateMovingAverage(data, 5)
  const ma10Values = calculateMovingAverage(data, 10)
  const ma20Values = calculateMovingAverage(data, 20)
  const macd = calculateMacd(data)
  const latest = data.at(-1)
  const previous = data.at(-2)
  const latestIndex = data.length - 1
  const latestMa5 = ma5Values.at(-1)
  const latestMa10 = ma10Values.at(-1)
  const latestMa20 = ma20Values.at(-1)
  const previousMa10 = ma10Values.at(-2)
  const previousMa20 = ma20Values.at(-2)
  const ma20FiveDaysAgo = ma20Values.length >= 5 ? ma20Values.at(-5) : null
  const ma20FlatOrUp = latestMa20 != null && ma20FiveDaysAgo != null ? latestMa20 >= ma20FiveDaysAgo * 0.998 : null
  const ma20Down = latestMa20 != null && ma20FiveDaysAgo != null ? latestMa20 < ma20FiveDaysAgo * 0.998 : null
  const previousFiveAmountAverage = data.length >= 6 ? average(data.slice(-6, -1).map((item) => item.amount ?? 0).filter((value) => value > 0)) : null
  const amountSignal = latest && latest.amount != null && previousFiveAmountAverage != null
    ? {
      passed: latest.amount > previousFiveAmountAverage * 1.2,
      strongPassed: latest.amount > previousFiveAmountAverage * 1.3,
      detail: `成交额 ${formatAmountLabel(latest.amount)} / 过去5日均额 ${formatAmountLabel(previousFiveAmountAverage)}`,
    }
    : {
      passed: null,
      strongPassed: null,
      detail: '成交额数据不足，等待行情刷新补齐',
    }
  const highestClose60 = data.length > 0 ? Math.max(...data.slice(-60).map((item) => item.close)) : null
  const drawdownPct = latest && highestClose60 && highestClose60 > 0 ? (highestClose60 - latest.close) / highestClose60 * 100 : null
  const hs300Change = benchmarks.hs300?.data.at(-1)?.change_pct ?? null
  const csiA500Change = benchmarks.csiA500?.data.at(-1)?.change_pct ?? null
  const hasBenchmark = hs300Change != null || csiA500Change != null
  const strongerThanBenchmark = latest && hasBenchmark
    ? [hs300Change, csiA500Change].some((value) => value != null && latest.change > value)
    : null
  const latestDif = macd.dif.at(-1)
  const latestDea = macd.dea.at(-1)
  const latestMacdHistogram = macd.histogram.at(-1)
  const previousMacdHistogram = macd.histogram.at(-2)
  const macdTurnedStrong = latestDif != null && latestDea != null && latestMacdHistogram != null
    ? latestDif > latestDea || (previousMacdHistogram != null && previousMacdHistogram <= 0 && latestMacdHistogram > 0)
    : null
  const rsi14 = calculateRsi(data, 14)
  const rsiHealthy = rsi14 != null ? rsi14 >= 45 && rsi14 <= 70 : null
  const rsiOverheated = rsi14 != null ? rsi14 > 75 : false
  const distanceFromMa20Pct = latest && latestMa20 && latestMa20 > 0 ? (latest.close - latestMa20) / latestMa20 * 100 : null
  const tooFarFromMa20 = distanceFromMa20Pct != null ? distanceFromMa20Pct > 7 : false
  const previousLongUpperShadow = previous ? hasLongUpperShadow(previous) : false
  const failedRepair = Boolean(previous && latest && previousLongUpperShadow && latest.close <= Math.max(previous.open, previous.close))
  const latestAmountStrong = amountSignal.strongPassed === true
  const latestLongUpperShadow = latest ? hasLongUpperShadow(latest) : false
  const latestLongUpperWithVolume = latestLongUpperShadow && latestAmountStrong

  const priceAboveMa20 = latest && latestMa20 != null ? latest.close > latestMa20 : null
  const ma5AboveMa10 = latestMa5 != null && latestMa10 != null ? latestMa5 > latestMa10 : null
  const buyRequiredChecks: RuleCheck[] = [
    {
      label: '收盘站上 MA20',
      passed: priceAboveMa20,
      detail: `收盘 ${formatSignalNumber(latest?.close)} / MA20 ${formatSignalNumber(latestMa20)}`,
    },
    {
      label: 'MA5 高于 MA10',
      passed: ma5AboveMa10,
      detail: `MA5 ${formatSignalNumber(latestMa5)} / MA10 ${formatSignalNumber(latestMa10)}`,
    },
    {
      label: 'MA20 走平或上行',
      passed: ma20FlatOrUp,
      detail: `MA20 ${formatSignalNumber(latestMa20)} / 5日前 ${formatSignalNumber(ma20FiveDaysAgo)}`,
    },
  ]
  const buyBonusChecks: RuleCheck[] = [
    {
      label: '成交额放大 1.2x',
      passed: amountSignal.passed,
      detail: amountSignal.detail,
    },
    {
      label: '强于沪深300或中证A500',
      passed: strongerThanBenchmark,
      detail: `ETF ${formatSignedPct(latest?.change)} / 沪深300 ${formatSignedPct(hs300Change)} / 中证A500 ${formatSignedPct(csiA500Change)}`,
    },
    {
      label: 'MACD 转强',
      passed: macdTurnedStrong,
      detail: `DIF ${formatSignalNumber(latestDif, 4)} / DEA ${formatSignalNumber(latestDea, 4)} / 柱 ${formatSignalNumber(latestMacdHistogram, 4)}`,
    },
    {
      label: 'RSI 45-70',
      passed: rsiHealthy,
      detail: `RSI ${formatSignalNumber(rsi14, 2)}`,
    },
  ]
  const buyChecks: RuleCheck[] = [...buyRequiredChecks, ...buyBonusChecks]
  const requiredBuyPassed = buyRequiredChecks.every((check) => check.passed === true)
  const bonusPassedCount = buyBonusChecks.filter((check) => check.passed === true).length
  const avoidChase = rsiOverheated || tooFarFromMa20

  const belowMa10 = latest && latestMa10 != null ? latest.close < latestMa10 : null
  const previousBelowMa10 = previous && previousMa10 != null ? previous.close < previousMa10 : false
  const confirmedBelowMa10 = belowMa10 === true && (previousBelowMa10 || amountSignal.strongPassed === true)
  const belowMa20 = latest && latestMa20 != null ? latest.close < latestMa20 : null
  const previousBelowMa20 = previous && previousMa20 != null ? previous.close < previousMa20 : false
  const confirmedBelowMa20 = belowMa20 === true && (previousBelowMa20 || ma20Down === true)
  const clearlyWeakerThanBenchmark = latest && hasBenchmark
    ? [hs300Change, csiA500Change].some((value) => value != null && latest.change < value - 0.8)
    : null

  const sellChecks: RuleCheck[] = [
    {
      label: 'MA20 破位确认，清仓',
      passed: confirmedBelowMa20,
      detail: `收盘 ${formatSignalNumber(latest?.close)} / MA20 ${formatSignalNumber(latestMa20)}；${previousBelowMa20 ? '连续2日低于MA20' : ma20Down ? 'MA20下行确认' : '尚未确认'}`,
    },
    {
      label: 'MA10 破位确认，减仓',
      passed: confirmedBelowMa10,
      detail: `收盘 ${formatSignalNumber(latest?.close)} / MA10 ${formatSignalNumber(latestMa10)}；${previousBelowMa10 ? '连续2日低于MA10' : amountSignal.strongPassed ? '放量跌破' : '尚未确认'}`,
    },
    {
      label: '60日高点回撤 5%-8%，移动止盈',
      passed: drawdownPct != null ? drawdownPct >= 5 && drawdownPct <= 8 && belowMa20 !== true : null,
      detail: `60日最高收盘 ${formatSignalNumber(highestClose60)} / 当前回撤 ${drawdownPct == null ? 'N/A' : `-${drawdownPct.toFixed(2)}%`}`,
    },
    {
      label: '放量长上影次日未修复，减仓',
      passed: previous && latest ? failedRepair : null,
      detail: previous && latest
        ? `前一日${previousLongUpperShadow ? '出现' : '未出现'}长上影，今日收盘 ${formatSignalNumber(latest.close)} / 前一日实体高点 ${formatSignalNumber(Math.max(previous.open, previous.close))}`
        : '需要至少两个交易日数据',
    },
    {
      label: '相对指数明显走弱',
      passed: clearlyWeakerThanBenchmark,
      detail: `ETF ${formatSignedPct(latest?.change)} / 沪深300 ${formatSignedPct(hs300Change)} / 中证A500 ${formatSignedPct(csiA500Change)}`,
    },
  ]

  if (data.length < 20 || latestIndex < 19) {
    return {
      action: 'insufficient',
      label: '数据不足',
      toneClassName: 'border-slate-200 bg-slate-50 text-slate-700',
      summary: '至少需要 20 个交易日 K 线才能判断 MA20 相关规则。',
      buyChecks,
      sellChecks,
    }
  }

  if (confirmedBelowMa20 || (belowMa20 && ma20Down && clearlyWeakerThanBenchmark)) {
    return {
      action: 'clear',
      label: '清仓',
      toneClassName: 'border-green-200 bg-green-50 text-green-700',
      summary: 'MA20 破位已确认，或破位同时伴随趋势下行与相对走弱，优先执行清仓风控。',
      buyChecks,
      sellChecks,
    }
  }

  if (confirmedBelowMa10 || failedRepair) {
    return {
      action: 'reduce',
      label: '减仓',
      toneClassName: 'border-amber-200 bg-amber-50 text-amber-700',
      summary: confirmedBelowMa10 ? 'MA10 破位已确认，按该方案触发减仓观察。' : '前一日长上影后未修复，按该方案触发减仓观察。',
      buyChecks,
      sellChecks,
    }
  }

  if (drawdownPct != null && drawdownPct >= 5 && drawdownPct <= 8 && belowMa20 !== true) {
    return {
      action: 'take_profit',
      label: '移动止盈',
      toneClassName: 'border-blue-200 bg-blue-50 text-blue-700',
      summary: '从 60 日高点回撤进入 5%-8% 区间，但尚未跌破 MA20，适合执行移动止盈纪律。',
      buyChecks,
      sellChecks,
    }
  }

  if (requiredBuyPassed && bonusPassedCount >= 3 && !avoidChase) {
    return {
      action: 'buy',
      label: '正常买入',
      toneClassName: 'border-red-200 bg-red-50 text-red-700',
      summary: '趋势必要条件成立，且成交额、相对强弱、MACD、RSI 中至少 3 项加分条件满足。',
      buyChecks,
      sellChecks,
    }
  }

  if (requiredBuyPassed && bonusPassedCount >= 2 && !avoidChase) {
    return {
      action: 'buy',
      label: '试探买入',
      toneClassName: 'border-orange-200 bg-orange-50 text-orange-700',
      summary: '趋势必要条件成立，且至少 2 项强度条件满足，适合小仓位试探。',
      buyChecks,
      sellChecks,
    }
  }

  if (requiredBuyPassed && avoidChase) {
    return {
      action: 'watch',
      label: '等待回踩',
      toneClassName: 'border-slate-200 bg-slate-50 text-slate-700',
      summary: `趋势条件成立，但${rsiOverheated ? 'RSI过热' : '价格距离MA20过远'}，不宜追高。`,
      buyChecks,
      sellChecks,
    }
  }

  if (latestLongUpperWithVolume) {
    return {
      action: 'watch',
      label: '观察修复',
      toneClassName: 'border-slate-200 bg-slate-50 text-slate-700',
      summary: '当日出现放量长上影，需要观察次日能否重新站上实体高点。',
      buyChecks,
      sellChecks,
    }
  }

  return {
    action: 'watch',
    label: '观察',
    toneClassName: 'border-slate-200 bg-slate-50 text-slate-700',
    summary: '当前没有满足分层买入条件，也未触发确认后的卖出条件。',
    buyChecks,
    sellChecks,
  }
}

export function buildTradeSignalFromHistory(
  history: MarketHistoryResponse | null | undefined,
  benchmarks: Record<BenchmarkKey, MarketHistoryResponse | null>,
): TradeSignal {
  const data = (history?.data || []).map((k) => ({
    date: k.trade_date.slice(5),
    fullDate: k.trade_date,
    provisional: k.provisional || false,
    open: k.open_price,
    close: k.close_price,
    high: k.high_price,
    low: k.low_price,
    volume: k.volume,
    amount: k.amount ?? null,
    change: k.change_pct,
  }))
  return buildTradeSignal(data, benchmarks)
}

export function getShanghaiDateKey(date: Date) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function isCurrentShanghaiIntradayPoint(item: MarketHistoryResponse['data'][number]) {
  if (!item.trade_time) return false
  const tradeTime = new Date(item.trade_time)
  if (Number.isNaN(tradeTime.getTime())) return false
  const now = new Date()
  if (tradeTime.getTime() > now.getTime() + 60_000) return false
  return getShanghaiDateKey(tradeTime) === getShanghaiDateKey(now)
}

export function calculateRsi(data: CandlePoint[], period = 14) {
  if (data.length <= period) return null
  const closes = data.map((item) => item.close)
  let gains = 0
  let losses = 0
  for (let index = closes.length - period; index < closes.length; index += 1) {
    const change = closes[index] - closes[index - 1]
    if (change > 0) gains += change
    else losses += Math.abs(change)
  }
  if (losses === 0) return 100
  const rs = gains / losses
  return 100 - (100 / (1 + rs))
}

export function CandlestickChart({
  data,
  costPrice,
  visibleIndicators,
  className = 'h-80',
  partialMovingAverage = false,
  timeframe = 'daily',
}: {
  data: CandlePoint[]
  costPrice?: number | null
  visibleIndicators: Record<IndicatorLineKey, boolean>
  className?: string
  partialMovingAverage?: boolean
  timeframe?: 'daily' | 'intraday'
}) {
  const width = 960
  const height = 320
  const padding = { top: 16, right: 86, bottom: 26, left: 56 }
  const volumeHeight = 72
  const volumeGap = 14
  const priceHeight = height - padding.top - padding.bottom - volumeHeight - volumeGap
  const priceBottom = padding.top + priceHeight
  const volumeTop = priceBottom + volumeGap
  const chartWidth = width - padding.left - padding.right
  const candleStep = chartWidth / Math.max(data.length, 1)
  const candleWidth = Math.max(4, Math.min(12, candleStep * 0.58))
  const averageLabel = (label: string) => timeframe === 'intraday' ? `${label}m` : label
  const macdLabel = timeframe === 'intraday' ? '1m MACD' : '日线 MACD'
  const movingAverages = [
    { key: 'ma5', label: averageLabel('MA5'), color: '#2563eb', values: calculateMovingAverage(data, 5, partialMovingAverage) },
    { key: 'ma10', label: averageLabel('MA10'), color: '#9333ea', values: calculateMovingAverage(data, 10, partialMovingAverage) },
    { key: 'ma20', label: averageLabel('MA20'), color: '#f97316', values: calculateMovingAverage(data, 20, partialMovingAverage) },
    { key: 'ma60', label: averageLabel('MA60'), color: '#475569', values: calculateMovingAverage(data, 60, partialMovingAverage) },
  ] satisfies Array<{ key: IndicatorLineKey; label: string; color: string; values: Array<number | null> }>
  const bollingerBands = calculateBollingerBands(data)
  const bollLines = [
    { key: 'boll-upper', label: 'BOLL上轨', color: '#0ea5e9', values: bollingerBands.upper, dashArray: '4 3' },
    { key: 'boll-middle', label: 'BOLL中轨', color: '#64748b', values: bollingerBands.middle },
    { key: 'boll-lower', label: 'BOLL下轨', color: '#0ea5e9', values: bollingerBands.lower, dashArray: '4 3' },
  ]
  const visibleAverages = movingAverages.filter((average) => visibleIndicators[average.key])
  const visibleBollLines = visibleIndicators.boll ? bollLines : []
  const visibleIndicatorLines = [...visibleAverages, ...visibleBollLines]
  const macd = calculateMacd(data)
  const macdMaxAbs = Math.max(
    ...macd.dif.map((value) => Math.abs(value)),
    ...macd.dea.map((value) => Math.abs(value)),
    ...macd.histogram.map((value) => Math.abs(value)),
    0.0001,
  )
  const validPrices = [
    ...data.flatMap((item) => [item.high, item.low]),
    ...movingAverages.flatMap((average) => average.values.filter((value): value is number => value != null)),
    ...bollLines.flatMap((line) => line.values.filter((value): value is number => value != null)),
  ]
  const baseMin = Math.min(...validPrices)
  const baseMax = Math.max(...validPrices)
  const includeCostLine = costPrice != null && costPrice > 0
  const spread = Math.max(baseMax - baseMin, baseMax * 0.02, 0.01)
  const priceMin = Math.max(0, Math.min(baseMin, includeCostLine ? costPrice : baseMin) - spread * 0.08)
  const priceMax = Math.max(baseMax, includeCostLine ? costPrice : baseMax) + spread * 0.08
  const volumeMax = Math.max(...data.map((item) => item.volume), 1)
  const priceTicks = Array.from({ length: 5 }, (_, index) => priceMin + ((priceMax - priceMin) / 4) * index)
  const xTickIndexes = Array.from(
    new Set([0, Math.floor(data.length * 0.25), Math.floor(data.length * 0.5), Math.floor(data.length * 0.75), data.length - 1].filter((index) => index >= 0 && index < data.length))
  )

  const getX = (index: number) => padding.left + candleStep * index + candleStep / 2
  const getPriceY = (value: number) => priceBottom - ((value - priceMin) / Math.max(priceMax - priceMin, 0.0001)) * priceHeight
  const getVolumeY = (value: number) => volumeTop + volumeHeight - (value / volumeMax) * volumeHeight
  const getMacdY = (value: number) => volumeTop + volumeHeight / 2 - (value / macdMaxAbs) * (volumeHeight * 0.42)
  const macdZeroY = getMacdY(0)
  const costY = includeCostLine ? getPriceY(costPrice) : null
  const changeLabel = timeframe === 'intraday' ? '分钟涨跌' : '日涨跌'

  return (
    <div className={`${className} rounded-lg border bg-background/40 p-2`}>
      <div className="mb-2 flex items-center justify-between gap-2 px-2 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-sm bg-red-500" />
            阳线
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" />
            阴线
          </span>
          {includeCostLine ? (
            <span className="inline-flex items-center gap-1">
              <span className="h-0.5 w-4 bg-amber-500" />
              成本线
            </span>
          ) : null}
          {visibleAverages.map((average) => (
            <span key={average.key} className="inline-flex items-center gap-1">
              <span className="h-0.5 w-4" style={{ backgroundColor: average.color }} />
              {average.label}
            </span>
          ))}
          {visibleIndicators.boll ? (
            <span className="inline-flex items-center gap-1">
              <span className="h-0.5 w-4 bg-sky-500" />
              BOLL
            </span>
          ) : null}
          {visibleIndicators.macd ? (
            <>
              <span className="inline-flex items-center gap-1">
                <span className="h-0.5 w-4 bg-cyan-600" />
                {macdLabel} DIF
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-0.5 w-4 bg-amber-500" />
                DEA
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm bg-red-500" />
                {macdLabel}柱
              </span>
            </>
          ) : null}
        </div>
        <span>上方为价格，下方为{visibleIndicators.macd ? macdLabel : '成交量'}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[calc(100%-24px)] w-full">
        {priceTicks.map((tick) => {
          const y = getPriceY(tick)
          return (
            <g key={`price-tick-${tick}`}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="currentColor" strokeOpacity="0.12" />
              <text x={padding.left - 10} y={y + 4} textAnchor="end" fontSize="11" fill="currentColor" opacity="0.6">
                {formatAxisValue(tick)}
              </text>
            </g>
          )
        })}

        <line x1={padding.left} x2={width - padding.right} y1={priceBottom} y2={priceBottom} stroke="currentColor" strokeOpacity="0.2" />
        <line x1={padding.left} x2={width - padding.right} y1={volumeTop} y2={volumeTop} stroke="currentColor" strokeOpacity="0.16" />
        <text x={padding.left - 10} y={volumeTop + 4} textAnchor="end" fontSize="11" fill="currentColor" opacity="0.6">
          {formatVolumeLabel(volumeMax)}
        </text>
        <text x={padding.left - 10} y={volumeTop + volumeHeight + 4} textAnchor="end" fontSize="11" fill="currentColor" opacity="0.4">
          0
        </text>
        {visibleIndicators.macd ? (
          <g>
            <line x1={padding.left} x2={width - padding.right} y1={macdZeroY} y2={macdZeroY} stroke="currentColor" strokeOpacity="0.14" strokeDasharray="3 3" />
            <text x={width - padding.right + 6} y={macdZeroY + 4} fontSize="11" fill="currentColor" opacity="0.45">
              {macdLabel} 0
            </text>
          </g>
        ) : null}

        {costY != null ? (
          <g>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={costY}
              y2={costY}
              stroke="#f59e0b"
              strokeWidth="1.2"
              strokeDasharray="5 4"
            />
            <text x={width - padding.right + 6} y={costY + 4} fontSize="11" fill="#f59e0b">
              成本 {costPrice?.toFixed(3)}
            </text>
          </g>
        ) : null}

        {visibleIndicators.macd ? (
          <g>
            {macd.histogram.map((value, index) => {
              const x = getX(index)
              const y = getMacdY(value)
              const isUp = value >= 0
              return (
                <rect
                  key={`macd-histogram-${data[index].fullDate}`}
                  x={x - candleWidth / 2}
                  y={Math.min(y, macdZeroY)}
                  width={candleWidth}
                  height={Math.max(Math.abs(y - macdZeroY), 1)}
                  rx="1"
                  fill={isUp ? '#ef4444' : '#10b981'}
                  fillOpacity="0.56"
                />
              )
            })}
            <polyline
              points={macd.dif.map((value, index) => `${getX(index)},${getMacdY(value)}`).join(' ')}
              fill="none"
              stroke="#0891b2"
              strokeWidth="1.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <polyline
              points={macd.dea.map((value, index) => `${getX(index)},${getMacdY(value)}`).join(' ')}
              fill="none"
              stroke="#f59e0b"
              strokeWidth="1.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <text x={width - padding.right + 6} y={volumeTop + 14} fontSize="11" fill="#0891b2">
              DIF {macd.dif[macd.dif.length - 1]?.toFixed(4)}
            </text>
            <text x={width - padding.right + 6} y={volumeTop + 28} fontSize="11" fill="#f59e0b">
              DEA {macd.dea[macd.dea.length - 1]?.toFixed(4)}
            </text>
            <text x={width - padding.right + 6} y={volumeTop + 42} fontSize="11" fill={macd.histogram[macd.histogram.length - 1] >= 0 ? '#ef4444' : '#10b981'}>
              柱 {macd.histogram[macd.histogram.length - 1]?.toFixed(4)}
            </text>
          </g>
        ) : null}

        {data.map((item, index) => {
          const x = getX(index)
          const wickTop = getPriceY(item.high)
          const wickBottom = getPriceY(item.low)
          const openY = getPriceY(item.open)
          const closeY = getPriceY(item.close)
          const bodyTop = Math.min(openY, closeY)
          const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5)
          const bodyY = bodyHeight <= 1.5 ? bodyTop - 0.75 : bodyTop
          const isUp = item.close >= item.open
          const candleColor = isUp ? '#ef4444' : '#10b981'
          const isProvisional = item.provisional === true
          const volumeY = getVolumeY(item.volume)
          const volumeHeightValue = volumeTop + volumeHeight - volumeY
          return (
            <g key={item.fullDate}>
              <line x1={x} x2={x} y1={wickTop} y2={wickBottom} stroke={candleColor} strokeWidth="1.2" />
              <rect
                x={x - candleWidth / 2}
                y={bodyY}
                width={candleWidth}
                height={bodyHeight}
                rx="1"
                fill={candleColor}
                fillOpacity={isProvisional ? 0.42 : isUp ? 0.88 : 0.82}
                stroke={isProvisional ? candleColor : undefined}
                strokeWidth={isProvisional ? 1.4 : undefined}
                strokeDasharray={isProvisional ? '3 2' : undefined}
              />
              {isProvisional ? (
                <text x={x} y={Math.max(padding.top + 10, bodyY - 6)} textAnchor="middle" fontSize="10" fill={candleColor} fontWeight="600">
                  盘中
                </text>
              ) : null}
              {!visibleIndicators.macd ? (
                <rect
                  x={x - candleWidth / 2}
                  y={volumeY}
                  width={candleWidth}
                  height={Math.max(volumeHeightValue, 1)}
                  rx="1"
                  fill={candleColor}
                  fillOpacity="0.24"
                />
              ) : null}
              {xTickIndexes.includes(index) ? (
                <text x={x} y={height - 6} textAnchor="middle" fontSize="11" fill="currentColor" opacity="0.6">
                  {item.date}
                </text>
              ) : null}
              <title>
                {`${item.fullDate}${isProvisional ? ' 盘中估算' : ''}
开 ${item.open.toFixed(3)} / 高 ${item.high.toFixed(3)} / 低 ${item.low.toFixed(3)} / 收 ${item.close.toFixed(3)}
${changeLabel} ${item.change >= 0 ? '+' : ''}${item.change.toFixed(2)}% / 量 ${formatVolumeLabel(item.volume)}`}
              </title>
            </g>
          )
        })}

        {visibleIndicatorLines.map((line, lineIndex) => {
          const validPoints = line.values
            .map((value, index) => value == null ? null : { value, index, x: getX(index), y: getPriceY(value) })
            .filter((point): point is { value: number; index: number; x: number; y: number } => point != null)
          const points = validPoints.map((point) => `${point.x},${point.y}`).join(' ')
          const lastPoint = validPoints.at(-1)

          return validPoints.length > 0 ? (
            <g key={line.key}>
              {validPoints.length >= 2 ? (
                <polyline
                  points={points}
                  fill="none"
                  stroke={line.color}
                  strokeWidth="2"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={'dashArray' in line ? line.dashArray : undefined}
                />
              ) : null}
              {validPoints.length === 1 ? (
                <circle cx={validPoints[0].x} cy={validPoints[0].y} r="3.5" fill={line.color} stroke="white" strokeWidth="1.2" />
              ) : null}
              {lastPoint ? (
                <text
                  x={Math.min(lastPoint.x + 8, width - padding.right + 8)}
                  y={Math.max(padding.top + 10, Math.min(lastPoint.y - 6 + lineIndex * 11, priceBottom - 6))}
                  fontSize="11"
                  fontWeight="600"
                  fill={line.color}
                >
                  {line.label} {lastPoint.value.toFixed(3)}
                </text>
              ) : null}
            </g>
          ) : null
        })}
      </svg>
    </div>
  )
}


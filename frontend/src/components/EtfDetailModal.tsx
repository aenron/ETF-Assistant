import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X, BarChart3, Activity, Calendar, Lightbulb, Loader2, RefreshCw, Clock, Database } from 'lucide-react'
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

type IndicatorLineKey = 'ma5' | 'ma10' | 'ma20' | 'boll' | 'macd'

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

type CandlePoint = {
  date: string
  fullDate: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  change: number
}

function formatAxisValue(value: number) {
  if (!Number.isFinite(value)) {
    return '-'
  }
  return value.toFixed(3)
}

function formatVolumeLabel(value: number) {
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

function calculateMovingAverage(data: CandlePoint[], period: number) {
  return data.map((_, index) => {
    if (index < period - 1) return null
    const window = data.slice(index - period + 1, index + 1)
    const sum = window.reduce((total, item) => total + item.close, 0)
    return sum / period
  })
}

function findLastNumberIndex(values: Array<number | null>) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index] != null) return index
  }
  return -1
}

function calculateBollingerBands(data: CandlePoint[], period = 20, multiplier = 2) {
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

function calculateEma(values: number[], period: number) {
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

function calculateMacd(data: CandlePoint[]) {
  const closes = data.map((item) => item.close)
  const ema12 = calculateEma(closes, 12)
  const ema26 = calculateEma(closes, 26)
  const dif = closes.map((_, index) => ema12[index] - ema26[index])
  const dea = calculateEma(dif, 9)
  const histogram = dif.map((value, index) => (value - dea[index]) * 2)

  return { dif, dea, histogram }
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

function CandlestickChart({
  data,
  costPrice,
  visibleIndicators,
}: {
  data: CandlePoint[]
  costPrice?: number | null
  visibleIndicators: Record<IndicatorLineKey, boolean>
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
  const movingAverages = [
    { key: 'ma5', label: 'MA5', color: '#2563eb', values: calculateMovingAverage(data, 5) },
    { key: 'ma10', label: 'MA10', color: '#9333ea', values: calculateMovingAverage(data, 10) },
    { key: 'ma20', label: 'MA20', color: '#f97316', values: calculateMovingAverage(data, 20) },
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

  return (
    <div className="h-80 rounded-lg border bg-background/40 p-2">
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
                DIF
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-0.5 w-4 bg-amber-500" />
                DEA
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2.5 w-2.5 rounded-sm bg-red-500" />
                MACD柱
              </span>
            </>
          ) : null}
        </div>
        <span>上方为价格，下方为{visibleIndicators.macd ? 'MACD' : '成交量'}</span>
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
              MACD 0
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

        {visibleIndicatorLines.map((line, lineIndex) => {
          const points = line.values
            .map((value, index) => value == null ? null : `${getX(index)},${getPriceY(value)}`)
            .filter((point): point is string => point != null)
            .join(' ')
          const lastIndex = findLastNumberIndex(line.values)
          const lastValue = lastIndex >= 0 ? line.values[lastIndex] : null

          return points ? (
            <g key={line.key}>
              <polyline
                points={points}
                fill="none"
                stroke={line.color}
                strokeWidth="1.6"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={'dashArray' in line ? line.dashArray : undefined}
              />
              {lastValue != null ? (
                <text
                  x={Math.min(getX(lastIndex) + 8, width - padding.right + 8)}
                  y={Math.max(padding.top + 10, Math.min(getPriceY(lastValue) - 6 + lineIndex * 11, priceBottom - 6))}
                  fontSize="11"
                  fontWeight="600"
                  fill={line.color}
                >
                  {line.label} {lastValue.toFixed(3)}
                </text>
              ) : null}
            </g>
          ) : null
        })}

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
                fillOpacity={isUp ? 0.88 : 0.82}
              />
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
                {`${item.fullDate}
开 ${item.open.toFixed(3)} / 高 ${item.high.toFixed(3)} / 低 ${item.low.toFixed(3)} / 收 ${item.close.toFixed(3)}
涨跌 ${item.change >= 0 ? '+' : ''}${item.change.toFixed(2)}% / 量 ${formatVolumeLabel(item.volume)}`}
              </title>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export function EtfDetailModal({ portfolio: p, onClose }: EtfDetailModalProps) {
  const [activeTab, setActiveTab] = useState<'chart' | 'advice' | 'profile'>('chart')
  const [visibleIndicators, setVisibleIndicators] = useState<Record<IndicatorLineKey, boolean>>({
    ma5: true,
    ma10: true,
    ma20: true,
    boll: false,
    macd: false,
  })
  const [historyData, setHistoryData] = useState<MarketHistoryResponse | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [profile, setProfile] = useState<EtfProfileResponse | null>(null)
  const [profileLoading, setProfileLoading] = useState(true)
  const [advice, setAdvice] = useState<AdviceResponse | null>(null)
  const [adviceLoading, setAdviceLoading] = useState(false)
  const [latestAdvice, setLatestAdvice] = useState<AdviceLogResponse | null>(null)
  const [latestLoading, setLatestLoading] = useState(true)

  useEffect(() => {
    fetchHistory()
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
      const res = await marketApi.getHistory(p.etf_code, 60)
      setHistoryData(res.data)
    } catch (e) {
      console.error('Failed to fetch history:', e)
    } finally {
      setHistoryLoading(false)
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
      const res = await adviceApi.generateForPortfolio(p.id)
      setAdvice(res.data)
      // 刷新最新建议
      fetchLatestAdvice()
    } catch (e: any) {
      const msg = e?.code === 'ECONNABORTED'
        ? '请求超时，AI正在搜索最新信息，请稍后重试'
        : '获取建议失败'
      alert(msg)
    } finally {
      setAdviceLoading(false)
    }
  }

  const indicators = historyData?.indicators
  const klines = historyData?.data || []

  // K线图数据
  const chartData = klines.map(k => ({
    date: k.trade_date.slice(5), // MM-DD
    fullDate: k.trade_date,
    open: k.open_price,
    close: k.close_price,
    high: k.high_price,
    low: k.low_price,
    volume: k.volume,
    change: k.change_pct,
  }))
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

  const displayAdvice = advice || latestAdvice
  const profileErrors = profile ? visibleProfileErrors(profile.errors || []) : []
  const displayConfig = displayAdvice ? (adviceTypeConfig[displayAdvice.advice_type || 'hold'] || adviceTypeConfig.hold) : null
  const displayConfidence = displayAdvice ? (displayAdvice.confidence || 0) : 0
  const displayTime = displayAdvice?.created_at || null
  const indicatorOptions: Array<{ key: IndicatorLineKey; label: string; colorClassName: string }> = [
    { key: 'ma5', label: 'MA5', colorClassName: 'bg-blue-600' },
    { key: 'ma10', label: 'MA10', colorClassName: 'bg-purple-600' },
    { key: 'ma20', label: 'MA20', colorClassName: 'bg-orange-500' },
    { key: 'boll', label: 'BOLL', colorClassName: 'bg-sky-500' },
    { key: 'macd', label: 'MACD', colorClassName: 'bg-cyan-600' },
  ]
  const toggleIndicator = (key: IndicatorLineKey) => {
    setVisibleIndicators((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
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
            ETF资料
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {activeTab === 'chart' && (
            <>
              {/* K线图 */}
              <Card>
                <CardContent className="pt-4">
                  <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <h3 className="text-sm font-semibold">近60日走势</h3>
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {indicatorOptions.map((option) => (
                          <label key={option.key} className="inline-flex cursor-pointer items-center gap-1.5">
                            <input
                              type="checkbox"
                              checked={visibleIndicators[option.key]}
                              onChange={() => toggleIndicator(option.key)}
                              className="h-3.5 w-3.5 rounded border-muted-foreground/40 accent-primary"
                            />
                            <span className={`h-0.5 w-4 ${option.colorClassName}`} />
                            <span>{option.label}</span>
                          </label>
                        ))}
                      </div>
                      <Button size="sm" variant="ghost" onClick={fetchHistory} disabled={historyLoading}>
                        <RefreshCw className={`h-3.5 w-3.5 mr-1 ${historyLoading ? 'animate-spin' : ''}`} />
                        刷新
                      </Button>
                    </div>
                  </div>
                  {historyLoading ? (
                    <div className="h-64 flex items-center justify-center text-muted-foreground">
                      <Loader2 className="h-6 w-6 animate-spin mr-2" />
                      加载中...
                    </div>
                  ) : chartData.length > 0 ? (
                    <div className="h-80">
                      <CandlestickChart data={chartData} costPrice={p.cost_price} visibleIndicators={visibleIndicators} />
                    </div>
                  ) : (
                    <div className="h-64 flex items-center justify-center text-muted-foreground">
                      暂无K线数据
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* 技术指标 */}
              <Card>
                <CardContent className="pt-4">
                  <h3 className="text-sm font-semibold mb-3 flex items-center gap-1.5">
                    <Activity className="h-4 w-4" />
                    技术指标
                  </h3>
                  {indicators ? (
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
                        重新分析
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
                  <p className="text-muted-foreground mb-4">暂无决策建议</p>
                  <Button onClick={fetchAdvice} size="lg">
                    <Lightbulb className="h-4 w-4 mr-2" />
                    生成AI决策建议
                  </Button>
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
                  <p className="text-muted-foreground">正在加载ETF资料...</p>
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
                  <p className="text-muted-foreground mb-4">暂无ETF资料</p>
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

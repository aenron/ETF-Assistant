import { useEffect, useMemo, useState } from 'react'
import { Activity, ChevronDown, Clock3, Loader2, RefreshCw, Save } from 'lucide-react'

import { adminApi, macroApi, portfolioApi, type MacroCycleState, type MacroCycleStateCreate, type MacroIndicator, type MacroPhase, type MacroRegion, type MacroTrend, type PortfolioWithMarket } from '@/services/api'
import { getCurrentUser } from '@/services/authApi'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

type RegionMeta = { label: string; description: string; dca: string }

const regionMeta: Record<MacroRegion, RegionMeta> = {
  cn: { label: '中国宏观', description: '适用于 A 股宽基、国内行业、债券和部分港股 ETF。', dca: '重点看政策、信用、地产、PMI、CPI/PPI。' },
  us: { label: '美国宏观', description: '适用于纳指、标普、道琼斯、美元资产相关 ETF。', dca: '重点看美国增长、通胀、就业、利率和美债压力。' },
  global: { label: '全球流动性', description: '适用于黄金、商品、跨境风险偏好和汇率压力判断。', dca: '重点看美元、美债、VIX、黄金、原油和全球避险。' },
}

const phaseMeta: Record<MacroPhase, { label: string; tone: string; asset: string; dialTone: string }> = {
  recovery: { label: '复苏', tone: 'border-emerald-200 bg-emerald-50 text-emerald-700', asset: '宽基、成长、消费、科技', dialTone: 'bg-emerald-500' },
  overheating: { label: '过热', tone: 'border-amber-200 bg-amber-50 text-amber-700', asset: '商品、资源、能源、部分周期', dialTone: 'bg-amber-500' },
  stagflation: { label: '滞涨', tone: 'border-red-200 bg-red-50 text-red-700', asset: '黄金、现金、防御行业', dialTone: 'bg-red-500' },
  recession: { label: '衰退', tone: 'border-sky-200 bg-sky-50 text-sky-700', asset: '债券、现金、红利低波、防御', dialTone: 'bg-sky-500' },
}

const trendLabel: Record<MacroTrend, string> = { up: '上行', down: '下行', flat: '横盘', unclear: '不明确' }
const categoryLabel: Record<string, string> = { growth: '增长', inflation: '通胀', liquidity: '流动性', currency: '汇率', property: '地产', risk: '风险' }

const defaultForm = (region: MacroRegion): MacroCycleStateCreate => ({
  region,
  cycle_phase: 'recovery',
  growth_score: 50,
  inflation_score: 50,
  growth_trend: 'unclear',
  inflation_trend: 'unclear',
  confidence: 60,
  summary: '',
  dca_impact: '',
  source_note: '手动维护',
  source_type: 'manual',
  override_until: null,
})

function formatTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function scoreWidth(value: number) {
  return `${Math.max(0, Math.min(100, value))}%`
}


function macroDialVector(state: MacroCycleState) {
  const growthOffset = Math.max(-50, Math.min(50, state.growth_score - 50))
  const inflationOffset = Math.max(-50, Math.min(50, state.inflation_score - 50))
  const distance = Math.sqrt(growthOffset ** 2 + inflationOffset ** 2)
  const angle = Math.atan2(growthOffset, inflationOffset) * 180 / Math.PI
  const length = Math.max(18, Math.min(42, 18 + (distance / Math.sqrt(50 ** 2 + 50 ** 2)) * 24))
  const pointLeft = 50 + growthOffset * 0.72
  const pointTop = 50 - inflationOffset * 0.72
  return { angle, length, pointLeft, pointTop, distance }
}

function MacroClockDial({ state }: { state: MacroCycleState }) {
  const meta = phaseMeta[state.cycle_phase]
  const dial = macroDialVector(state)
  const phases: Array<{ key: MacroPhase; axis: string; note: string }> = [
    { key: 'overheating', axis: '增长上行 · 通胀上行', note: '商品 / 资源 / 防追高' },
    { key: 'recovery', axis: '增长上行 · 通胀下行', note: '权益 / 成长 / 消费' },
    { key: 'recession', axis: '增长下行 · 通胀下行', note: '债券 / 现金 / 防御' },
    { key: 'stagflation', axis: '增长下行 · 通胀上行', note: '黄金 / 现金 / 控风险' },
  ]

  return (
    <div className="space-y-4">
      <div className="relative mx-auto aspect-square w-full max-w-[360px]">
        <div
          className="absolute inset-0 rounded-full border shadow-inner"
          style={{
            background:
              'conic-gradient(from 0deg, rgb(254 243 199) 0deg 90deg, rgb(209 250 229) 90deg 180deg, rgb(224 242 254) 180deg 270deg, rgb(254 226 226) 270deg 360deg)',
          }}
        />
        <div className="absolute inset-[8%] rounded-full border border-white/80 bg-white/20" />
        <div className="absolute inset-[22%] rounded-full border border-white/90 bg-background/95 shadow-sm" />
        <div className="absolute right-7 top-7 text-right">
          <div className="text-sm font-semibold text-amber-700">过热</div>
          <div className="text-[11px] text-muted-foreground">增长上行 · 通胀上行</div>
        </div>
        <div className="absolute bottom-7 right-7 text-right">
          <div className="text-sm font-semibold text-emerald-700">复苏</div>
          <div className="text-[11px] text-muted-foreground">增长上行 · 通胀下行</div>
        </div>
        <div className="absolute bottom-7 left-7">
          <div className="text-sm font-semibold text-sky-700">衰退</div>
          <div className="text-[11px] text-muted-foreground">增长下行 · 通胀下行</div>
        </div>
        <div className="absolute left-7 top-7">
          <div className="text-sm font-semibold text-red-700">滞涨</div>
          <div className="text-[11px] text-muted-foreground">增长下行 · 通胀上行</div>
        </div>
        <div className="absolute inset-0 rounded-full border border-slate-200" />
        <div className="absolute left-1/2 top-1/2 w-1 origin-bottom -translate-x-1/2 -translate-y-full rounded-full bg-slate-900 shadow-sm transition-transform" style={{ height: `${dial.length}%`, transform: `translate(-50%, -100%) rotate(${dial.angle}deg)` }}>
          <div className={`absolute -top-1 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full ${meta.dialTone}`} />
        </div>
        <div className={`absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ring-background ${meta.dialTone}`} style={{ left: `${dial.pointLeft}%`, top: `${dial.pointTop}%` }} />
        <div className="absolute left-1/2 top-1/2 flex h-28 w-28 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border bg-background text-center shadow-sm">
          <Clock3 className="mb-1 h-4 w-4 text-muted-foreground" />
          <div className="text-xs text-muted-foreground">当前阶段</div>
          <div className="text-xl font-semibold">{meta.label}</div>
          <div className="mt-1 text-xs text-muted-foreground">置信度 {state.confidence.toFixed(0)}%</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">增长 {state.growth_score.toFixed(0)} · 通胀 {state.inflation_score.toFixed(0)}</div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {phases.map((phase) => {
          const item = phaseMeta[phase.key]
          const active = phase.key === state.cycle_phase
          return (
            <div key={phase.key} className={`rounded-lg border p-3 ${active ? item.tone : 'bg-muted/20 text-muted-foreground'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{item.label}</span>
                {active && <span className="rounded-full bg-background/70 px-2 py-0.5 text-[11px]">当前</span>}
              </div>
              <div className="mt-1 text-xs">{phase.axis}</div>
              <div className="mt-2 text-xs">{phase.note}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}


type RotationBucket = {
  name: string
  score: number
  action: string
  limit: string
  reason: string
}

type RotationEtfRecommendation = {
  code: string
  name: string
  bucketName: string
  macroScore: number
  dcaScore: number
  qualityScore: number
  finalScore: number
  currentWeight: number
  action: string
  dcaLabel: string
  reason: string
}

const bucketBase: RotationBucket[] = [
  { name: 'A股宽基', score: 0, action: '中性', limit: '25%-35%', reason: '等待中国宏观信号确认' },
  { name: 'A股成长', score: 0, action: '中性', limit: '15%-25%', reason: '受中国增长和流动性影响较大' },
  { name: '港股中概', score: 0, action: '观察', limit: '10%-20%', reason: '同时受中国增长、美国利率和全球风险偏好影响' },
  { name: '美股成长', score: 0, action: '中性', limit: '8%-18%', reason: '重点受美国增长、通胀和利率约束' },
  { name: '黄金商品', score: 0, action: '中性', limit: '8%-20%', reason: '受全球风险、通胀和避险需求影响' },
  { name: '债券现金', score: 0, action: '中性', limit: '15%-35%', reason: '作为组合波动缓冲' },
]

function clampScore(value: number) {
  return Math.max(-40, Math.min(40, value))
}

function actionFromScore(score: number) {
  if (score >= 18) return '增配'
  if (score >= 6) return '谨慎增配'
  if (score <= -18) return '降权'
  if (score <= -6) return '谨慎降权'
  return '观察'
}

function bucketTone(score: number) {
  if (score >= 18) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (score >= 6) return 'border-lime-200 bg-lime-50 text-lime-700'
  if (score <= -18) return 'border-red-200 bg-red-50 text-red-700'
  if (score <= -6) return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function inferPortfolioBucket(portfolio: PortfolioWithMarket) {
  const text = `${portfolio.etf_code} ${portfolio.etf_name || ''}`
  if (/货币|现金|短融|同业存单|国债|地方债|政金债|信用债|可转债|债券/.test(text)) return '债券现金'
  if (/黄金|白银|贵金属|原油|油气|能源|煤炭|有色|铜|铝|化工|豆粕|农产品/.test(text)) return '黄金商品'
  if (/纳指|纳斯达克|标普|道琼斯|美国|NASDAQ|S&P|SP500/i.test(text)) return '美股成长'
  if (/恒生|港股|中概|国企|H股|香港/.test(text)) return '港股中概'
  if (/创业板|科创|芯片|半导体|人工智能|AI|机器人|算力|通信|5G|软件|云计算|科技|新能源|光伏|锂电|电池|储能|风电|创新药|生物|医药/.test(text)) return 'A股成长'
  if (/沪深300|中证500|中证1000|上证50|A50|深证100|宽基|全指|红利|股息|消费|食品|饮料|白酒|银行|证券|券商|保险|金融|地产|军工|国防|农业/.test(text)) return 'A股宽基'
  return '其他'
}

function scoreDcaSignal(portfolio: PortfolioWithMarket) {
  const light = `${portfolio.dca_light || ''} ${portfolio.dca_candidate_light || ''} ${portfolio.dca_label || ''}`
  if (/deep_green|深绿/.test(light)) return 18
  if (/green|绿灯|浅绿|正式绿/.test(light)) return 12
  if (/red|红灯/.test(light)) return -22
  if (/yellow|黄灯/.test(light)) return 0
  return -4
}

function actionFromEtfScore(recommendation: Pick<RotationEtfRecommendation, 'finalScore' | 'macroScore' | 'dcaScore'> & { crossBorderAction?: string }) {
  if (recommendation.crossBorderAction === '不新增') return '不新增'
  if (recommendation.dcaScore <= -18) return '不新增'
  if (recommendation.finalScore >= 16 && recommendation.dcaScore > 0) return '优先增配'
  if (recommendation.finalScore >= 8) return '观察加仓'
  if (recommendation.finalScore <= -14) return '降权'
  if (recommendation.finalScore <= -6) return '谨慎降权'
  return '持有观察'
}

function buildEtfRecommendations(portfolios: PortfolioWithMarket[], buckets: RotationBucket[]): RotationEtfRecommendation[] {
  const bucketMap = Object.fromEntries(buckets.map((bucket) => [bucket.name, bucket])) as Record<string, RotationBucket>
  const totalValue = portfolios.reduce((sum, item) => sum + Math.max(0, Number(item.market_value || 0)), 0)

  return portfolios.map((portfolio) => {
    const bucketName = inferPortfolioBucket(portfolio)
    const bucket = bucketMap[bucketName]
    const macroScore = bucket?.score ?? 0
    const dcaScore = scoreDcaSignal(portfolio)
    const qualityScore = portfolio.dca_quality_score == null ? 0 : Math.max(-15, Math.min(15, (portfolio.dca_quality_score - 50) / 2))
    const crossBorderPenalty = portfolio.cross_border_risk?.is_cross_border ? portfolio.cross_border_risk.risk_level === 'high' ? -10 : -5 : 0
    const finalScore = Math.round(Math.max(-40, Math.min(40, macroScore * 0.55 + dcaScore * 0.3 + qualityScore * 0.15 + crossBorderPenalty)))
    const currentWeight = totalValue > 0 ? Number(portfolio.market_value || 0) / totalValue * 100 : 0
    const rec = { macroScore, dcaScore, finalScore, crossBorderAction: portfolio.cross_border_risk?.action }
    const action = actionFromEtfScore(rec)
    const dcaLabel = portfolio.dca_label || portfolio.dca_light || portfolio.dca_candidate_light || '暂无红绿灯'
    const reasonParts = [bucket?.reason || '未命中明确资产桶，先按中性处理']
    if (portfolio.dca_reason) reasonParts.push(portfolio.dca_reason)
    if (portfolio.cross_border_risk?.is_cross_border) reasonParts.push(`跨境风控：${portfolio.cross_border_risk.action}，单品种建议上限 ${(portfolio.cross_border_risk.max_position_hint * 100).toFixed(0)}%`)
    if (bucket?.limit) reasonParts.push(`资产桶建议上限 ${bucket.limit}`)

    return {
      code: portfolio.etf_code,
      name: portfolio.etf_name || portfolio.etf_code,
      bucketName,
      macroScore,
      dcaScore,
      qualityScore,
      finalScore,
      currentWeight,
      action,
      dcaLabel,
      reason: reasonParts.join('；'),
    }
  }).sort((a, b) => b.finalScore - a.finalScore || b.currentWeight - a.currentWeight)
}

function buildRotationAdvice(states: Record<MacroRegion, MacroCycleState | null>) {
  const buckets = bucketBase.map((item) => ({ ...item }))
  const byName = Object.fromEntries(buckets.map((item) => [item.name, item])) as Record<string, RotationBucket>
  const notes: string[] = []

  const cn = states.cn?.cycle_phase
  if (cn === 'recovery') {
    byName['A股宽基'].score += 24
    byName['A股成长'].score += 18
    byName['港股中概'].score += 8
    byName['债券现金'].score -= 8
    byName['A股宽基'].reason = '中国复苏，宽基和顺周期权益优先'
    byName['A股成长'].reason = '中国增长修复，成长资产可提高观察权重'
    notes.push('中国复苏：A股宽基和成长类 ETF 优先级上调。')
  } else if (cn === 'overheating') {
    byName['A股宽基'].score += 8
    byName['A股成长'].score -= 8
    byName['黄金商品'].score += 8
    byName['债券现金'].score += 6
    notes.push('中国过热：权益避免追高，商品和现金缓冲权重上调。')
  } else if (cn === 'stagflation') {
    byName['A股成长'].score -= 20
    byName['A股宽基'].score -= 8
    byName['黄金商品'].score += 14
    byName['债券现金'].score += 16
    notes.push('中国滞涨：降低成长和周期暴露，提高防御资产。')
  } else if (cn === 'recession') {
    byName['A股宽基'].score -= 12
    byName['A股成长'].score -= 18
    byName['债券现金'].score += 22
    notes.push('中国衰退：权益仓位上限下调，现金和债券缓冲优先。')
  }

  const us = states.us?.cycle_phase
  if (us === 'recovery') {
    byName['美股成长'].score += 18
    byName['港股中概'].score += 6
    notes.push('美国复苏：美股成长和跨境风险资产相对友好。')
  } else if (us === 'overheating') {
    byName['美股成长'].score -= 22
    byName['黄金商品'].score += 10
    byName['债券现金'].score += 8
    byName['美股成长'].reason = '美国过热，利率和估值压力限制美股成长上限'
    notes.push('美国过热：美股成长降权，只适合等待深绿或明显回撤。')
  } else if (us === 'stagflation') {
    byName['美股成长'].score -= 24
    byName['黄金商品'].score += 16
    byName['债券现金'].score += 12
    notes.push('美国滞涨：降低美股成长，提高黄金和现金缓冲。')
  } else if (us === 'recession') {
    byName['美股成长'].score -= 12
    byName['债券现金'].score += 18
    notes.push('美国衰退：跨境权益谨慎，防御资产权重提高。')
  }

  const global = states.global?.cycle_phase
  if (global === 'recovery') {
    byName['港股中概'].score += 8
    byName['美股成长'].score += 6
    byName['黄金商品'].score -= 6
    notes.push('全球风险偏好修复：跨境权益可适度提高。')
  } else if (global === 'overheating') {
    byName['黄金商品'].score += 12
    byName['美股成长'].score -= 6
    notes.push('全球过热：商品资产有支撑，权益避免追高。')
  } else if (global === 'stagflation') {
    byName['黄金商品'].score += 20
    byName['美股成长'].score -= 14
    byName['港股中概'].score -= 10
    byName['债券现金'].score += 10
    notes.push('全球滞涨：黄金商品和现金优先，跨境权益降权。')
  } else if (global === 'recession') {
    byName['黄金商品'].score += 18
    byName['债券现金'].score += 20
    byName['美股成长'].score -= 12
    byName['港股中概'].score -= 8
    byName['黄金商品'].reason = '全球衰退提高避险需求，黄金商品作为防御配置'
    notes.push('全球衰退：黄金、债券和现金缓冲权重上调。')
  }

  buckets.forEach((bucket) => {
    bucket.score = clampScore(bucket.score)
    bucket.action = actionFromScore(bucket.score)
  })

  const risks = [
    '红灯 ETF 不新增，黄灯 ETF 只观察或小额试探。',
    '单一跨境成长 ETF 不建议超过区域上限。',
    '单次调仓幅度建议控制在 10% 以内。',
    '宏观建议只决定方向和上限，实际买点仍以红绿灯为准。',
  ]

  return { buckets, notes, risks }
}

function MacroRotationAdvice({ states, portfolios }: { states: Record<MacroRegion, MacroCycleState | null>; portfolios: PortfolioWithMarket[] }) {
  const advice = useMemo(() => buildRotationAdvice(states), [states])
  const etfRecommendations = useMemo(() => buildEtfRecommendations(portfolios, advice.buckets), [portfolios, advice.buckets])
  const [holdingsAdviceOpen, setHoldingsAdviceOpen] = useState(false)
  return (
    <Card>
      <CardHeader>
        <CardTitle>ETF 轮动建议</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {advice.buckets.map((bucket) => (
            <div key={bucket.name} className={`rounded-lg border p-3 ${bucketTone(bucket.score)}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="font-semibold">{bucket.name}</div>
                <Badge variant="outline" className="bg-background/70">{bucket.action}</Badge>
              </div>
              <div className="mt-2 flex items-end justify-between gap-3">
                <div className="text-2xl font-semibold">{bucket.score > 0 ? '+' : ''}{bucket.score}</div>
                <div className="text-right text-xs">建议上限<br /><span className="font-medium">{bucket.limit}</span></div>
              </div>
              <p className="mt-2 text-xs leading-5">{bucket.reason}</p>
            </div>
          ))}
        </div>
        <div className="rounded-lg border">
          <button
            type="button"
            onClick={() => setHoldingsAdviceOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-3 border-b px-4 py-3 text-left text-sm font-semibold transition-colors hover:bg-muted/40"
          >
            <span>当前持仓 ETF 建议</span>
            <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
              {etfRecommendations.length ? `${etfRecommendations.length} 只` : '暂无持仓'}
              <ChevronDown className={`h-4 w-4 transition-transform ${holdingsAdviceOpen ? 'rotate-180' : ''}`} />
            </span>
          </button>
          {holdingsAdviceOpen && (etfRecommendations.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-muted-foreground">
                  <tr>
                    <th className="py-2 pl-4 pr-3">ETF</th>
                    <th className="py-2 pr-3">资产桶</th>
                    <th className="py-2 pr-3">宏观分</th>
                    <th className="py-2 pr-3">红绿灯</th>
                    <th className="py-2 pr-3">当前权重</th>
                    <th className="py-2 pr-3">综合分</th>
                    <th className="py-2 pr-4">动作</th>
                  </tr>
                </thead>
                <tbody>
                  {etfRecommendations.map((item) => (
                    <tr key={item.code} className="border-b last:border-0">
                      <td className="py-3 pl-4 pr-3">
                        <div className="font-medium">{item.name}</div>
                        <div className="text-xs text-muted-foreground">{item.code}</div>
                      </td>
                      <td className="py-3 pr-3">{item.bucketName}</td>
                      <td className="py-3 pr-3 font-mono">{item.macroScore > 0 ? '+' : ''}{item.macroScore}</td>
                      <td className="py-3 pr-3"><Badge variant="outline">{item.dcaLabel}</Badge></td>
                      <td className="py-3 pr-3 font-mono">{item.currentWeight.toFixed(1)}%</td>
                      <td className="py-3 pr-3 font-mono">{item.finalScore > 0 ? '+' : ''}{item.finalScore}</td>
                      <td className="py-3 pr-4">
                        <div className="font-medium">{item.action}</div>
                        <div className="mt-1 max-w-[360px] text-xs leading-5 text-muted-foreground">{item.reason}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">暂无持仓，当前仅展示资产桶级别建议。</div>
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="text-sm font-semibold">宏观解释</div>
            <div className="mt-3 space-y-2 text-sm text-muted-foreground">
              {advice.notes.map((note) => <div key={note}>{note}</div>)}
            </div>
          </div>
          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="text-sm font-semibold">风险约束</div>
            <div className="mt-3 space-y-2 text-sm text-muted-foreground">
              {advice.risks.map((risk) => <div key={risk}>{risk}</div>)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}


export function MacroClockPage() {
  const user = getCurrentUser()
  const isAdmin = Boolean(user?.is_admin)
  const [activeRegion, setActiveRegion] = useState<MacroRegion>('cn')
  const [currentByRegion, setCurrentByRegion] = useState<Record<MacroRegion, MacroCycleState | null>>({ cn: null, us: null, global: null })
  const [history, setHistory] = useState<MacroCycleState[]>([])
  const [indicators, setIndicators] = useState<MacroIndicator[]>([])
  const [form, setForm] = useState<MacroCycleStateCreate>(defaultForm('cn'))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [refreshingMacro, setRefreshingMacro] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error'>('success')
  const [manualPanelOpen, setManualPanelOpen] = useState(false)
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])

  const current = currentByRegion[activeRegion]

  const loadData = async (region: MacroRegion = activeRegion) => {
    setLoading(true)
    setMessage(null)
    try {
      const [cnRes, usRes, globalRes, historyRes, indicatorRes, portfolioRes] = await Promise.all([
        macroApi.getCurrent('cn'),
        macroApi.getCurrent('us'),
        macroApi.getCurrent('global'),
        macroApi.getHistory(region, 12),
        macroApi.getIndicators(region, 30),
        portfolioApi.getList(),
      ])
      setCurrentByRegion({ cn: cnRes.data, us: usRes.data, global: globalRes.data })
      setHistory(historyRes.data)
      setIndicators(indicatorRes.data)
      setPortfolios(portfolioRes.data)
      const currentRegionState = { cn: cnRes.data, us: usRes.data, global: globalRes.data }[region]
      setForm({
        region,
        cycle_phase: currentRegionState.cycle_phase,
        growth_score: currentRegionState.growth_score,
        inflation_score: currentRegionState.inflation_score,
        growth_trend: currentRegionState.growth_trend,
        inflation_trend: currentRegionState.inflation_trend,
        confidence: currentRegionState.confidence || 60,
        summary: currentRegionState.summary || '',
        dca_impact: currentRegionState.dca_impact || '',
        source_note: currentRegionState.source_note || '手动维护',
        source_type: 'manual',
        override_until: currentRegionState.override_until || null,
      })
    } catch (error: any) {
      console.error('Failed to load macro state:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '加载宏观时钟失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadData(activeRegion) }, [activeRegion])

  const refreshMacroData = async () => {
    setRefreshingMacro(true)
    setMessage(null)
    try {
      const res = await adminApi.refreshMacroData(activeRegion)
      setMessageTone(res.data.success ? 'success' : 'error')
      setMessage(res.data.errors.length ? `${res.data.message}，部分指标失败：${res.data.errors.join('；')}` : res.data.message)
      await loadData(activeRegion)
    } catch (error: any) {
      console.error('Failed to refresh macro data:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '自动采集宏观数据失败')
    } finally {
      setRefreshingMacro(false)
    }
  }

  const saveState = async () => {
    setSaving(true)
    setMessage(null)
    try {
      await adminApi.createMacroState({ ...form, region: activeRegion, source_type: 'manual', growth_score: Number(form.growth_score), inflation_score: Number(form.inflation_score), confidence: Number(form.confidence), override_until: form.override_until || null })
      setMessageTone('success')
      setMessage('宏观状态已保存')
      await loadData(activeRegion)
    } catch (error: any) {
      console.error('Failed to save macro state:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '保存宏观状态失败')
    } finally {
      setSaving(false)
    }
  }

  const meta = current ? phaseMeta[current.cycle_phase] : phaseMeta.recovery
  const messageClassName = messageTone === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'
  const indicatorRows = useMemo(() => current ? [
    { label: '增长分', value: current.growth_score, trend: trendLabel[current.growth_trend] },
    { label: '通胀分', value: current.inflation_score, trend: trendLabel[current.inflation_trend] },
    { label: '置信度', value: current.confidence, trend: `${current.confidence.toFixed(0)}%` },
  ] : [], [current])

  if (loading && !current) {
    return <Card><CardContent className="flex items-center justify-center py-12 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载宏观时钟中...</CardContent></Card>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">宏观时钟</h1>
          <p className="mt-1 text-sm text-muted-foreground">按中国、美国和全球流动性拆分宏观状态，服务国内 ETF 与跨境 ETF 的风险背景判断。</p>
        </div>
        <Button variant="outline" onClick={() => loadData(activeRegion)} disabled={loading} className="w-full sm:w-auto"><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
      </div>

      <div className="flex gap-2 overflow-x-auto rounded-lg border bg-muted/30 p-1">
        {(Object.keys(regionMeta) as MacroRegion[]).map((region) => (
          <button key={region} onClick={() => setActiveRegion(region)} className={`shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors ${activeRegion === region ? 'bg-background text-primary shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>{regionMeta[region].label}</button>
        ))}
      </div>

      {message && <div className={`rounded-lg border px-4 py-3 text-sm ${messageClassName}`}>{message}</div>}

      {current && (
        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0"><CardTitle>{regionMeta[activeRegion].label}</CardTitle><div className="flex items-center gap-2"><Badge variant="outline" className={current.source_type === 'manual' ? 'border-primary/30 bg-primary/10 text-primary' : 'border-slate-200 bg-slate-50 text-slate-600'}>{current.source_type === 'manual' ? '人工覆盖' : '自动'}</Badge><Badge variant="outline" className={meta.tone}>{meta.label}</Badge></div></CardHeader>
            <CardContent className="space-y-5">
              <p className="text-sm text-muted-foreground">{regionMeta[activeRegion].description}</p>
              <div className="grid gap-3 sm:grid-cols-3">
                {indicatorRows.map((item) => <div key={item.label} className="rounded-lg border bg-muted/20 p-3"><div className="text-xs text-muted-foreground">{item.label}</div><div className="mt-1 text-xl font-semibold">{item.value.toFixed(0)}</div><div className="mt-2 h-2 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: scoreWidth(item.value) }} /></div><div className="mt-2 text-xs text-muted-foreground">{item.trend}</div></div>)}
              </div>
              <div className="rounded-lg border bg-muted/20 p-4"><div className="flex items-center gap-2 text-sm font-semibold"><Activity className="h-4 w-4" />红绿灯影响</div><p className="mt-2 text-sm leading-6 text-muted-foreground">{current.dca_impact || regionMeta[activeRegion].dca}</p></div>
              <div className="grid gap-3 sm:grid-cols-2"><div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">偏好资产</div><div className="mt-1 text-sm font-medium">{activeRegion === 'global' ? '黄金、商品、现金、跨境风险控制' : meta.asset}</div></div><div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">更新时间</div><div className="mt-1 text-sm font-medium">{formatTime(current.observed_at)}</div></div></div>
              <p className="text-sm leading-6 text-muted-foreground">{current.summary || '暂无阶段说明。'}</p>
              <div className="text-xs text-muted-foreground">来源：{current.source_note || '手动维护'}{current.override_until ? ` · 覆盖至 ${formatTime(current.override_until)}` : ''}</div>
            </CardContent>
          </Card>
          <Card><CardHeader><CardTitle>{activeRegion === 'global' ? '流动性时钟' : '美林投资时钟'}</CardTitle></CardHeader><CardContent><MacroClockDial state={current} /></CardContent></Card>
        </div>
      )}

      <MacroRotationAdvice states={currentByRegion} portfolios={portfolios} />

      {isAdmin && (
        <Card>
          <CardHeader className="flex flex-col gap-3 space-y-0 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle>手动维护当前区域</CardTitle>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button variant="outline" size="sm" onClick={refreshMacroData} disabled={refreshingMacro || saving} className="w-full sm:w-auto">
                {refreshingMacro ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}采集当前区域
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setManualPanelOpen((value) => !value)} className="w-full sm:w-auto">
                {manualPanelOpen ? '收起手动维护' : '展开手动维护'}
                <ChevronDown className={`ml-2 h-4 w-4 transition-transform ${manualPanelOpen ? 'rotate-180' : ''}`} />
              </Button>
            </div>
          </CardHeader>
          {manualPanelOpen && <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="space-y-1.5"><span className="text-sm font-medium">区域</span><Input value={regionMeta[activeRegion].label} disabled /></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">周期阶段</span><select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={form.cycle_phase} onChange={(event) => setForm((prev) => ({ ...prev, cycle_phase: event.target.value as MacroPhase }))}>{Object.entries(phaseMeta).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}</select></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">增长分</span><Input type="number" min="0" max="100" value={form.growth_score} onChange={(event) => setForm((prev) => ({ ...prev, growth_score: Number(event.target.value) }))} /></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">通胀分</span><Input type="number" min="0" max="100" value={form.inflation_score} onChange={(event) => setForm((prev) => ({ ...prev, inflation_score: Number(event.target.value) }))} /></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">增长趋势</span><select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={form.growth_trend} onChange={(event) => setForm((prev) => ({ ...prev, growth_trend: event.target.value as MacroTrend }))}>{Object.entries(trendLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">通胀趋势</span><select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={form.inflation_trend} onChange={(event) => setForm((prev) => ({ ...prev, inflation_trend: event.target.value as MacroTrend }))}>{Object.entries(trendLabel).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">置信度</span><Input type="number" min="0" max="100" value={form.confidence} onChange={(event) => setForm((prev) => ({ ...prev, confidence: Number(event.target.value) }))} /></label>
              <label className="space-y-1.5"><span className="text-sm font-medium">来源说明</span><Input value={form.source_note || ''} onChange={(event) => setForm((prev) => ({ ...prev, source_note: event.target.value }))} /></label><label className="space-y-1.5"><span className="text-sm font-medium">覆盖到期</span><Input type="datetime-local" value={form.override_until ? form.override_until.slice(0, 16) : ''} onChange={(event) => setForm((prev) => ({ ...prev, override_until: event.target.value ? new Date(event.target.value).toISOString() : null }))} /></label>
            </div>
            <label className="block space-y-1.5"><span className="text-sm font-medium">阶段说明</span><textarea className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.summary || ''} onChange={(event) => setForm((prev) => ({ ...prev, summary: event.target.value }))} /></label>
            <label className="block space-y-1.5"><span className="text-sm font-medium">红绿灯影响说明</span><textarea className="min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.dca_impact || ''} onChange={(event) => setForm((prev) => ({ ...prev, dca_impact: event.target.value }))} /></label>
            <div className="flex flex-col justify-end gap-2 sm:flex-row"><Button onClick={saveState} disabled={saving || refreshingMacro} className="w-full sm:w-auto">{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}保存当前区域</Button></div>
          </CardContent>}
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>自动采集指标</CardTitle></CardHeader>
        <CardContent>{indicators.length ? <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="border-b text-left text-muted-foreground"><tr><th className="py-2 pr-3">指标</th><th className="py-2 pr-3">维度</th><th className="py-2 pr-3">周期</th><th className="py-2 pr-3">当前值</th><th className="py-2 pr-3">上期值</th><th className="py-2 pr-3">趋势</th><th className="py-2 pr-3">函数</th><th className="py-2">列名</th></tr></thead><tbody>{indicators.map((item) => <tr key={`${item.region}-${item.indicator_code}-${item.period}`} className="border-b last:border-0"><td className="py-3 pr-3 font-medium">{item.indicator_name}</td><td className="py-3 pr-3">{categoryLabel[item.category] || item.category}</td><td className="whitespace-nowrap py-3 pr-3">{item.period}</td><td className="py-3 pr-3 font-mono">{item.value.toFixed(2)}{item.unit || ''}</td><td className="py-3 pr-3 font-mono">{item.previous_value != null ? `${item.previous_value.toFixed(2)}${item.unit || ''}` : '-'}</td><td className="py-3 pr-3">{trendLabel[item.trend]}</td><td className="py-3 pr-3 text-muted-foreground">{item.source_function || item.source_note || item.source}</td><td className="py-3 text-muted-foreground">{item.source_column || '-'}</td></tr>)}</tbody></table></div> : <div className="py-8 text-center text-sm text-muted-foreground">当前区域暂无自动采集指标。</div>}</CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>历史记录</CardTitle></CardHeader>
        <CardContent>{history.length ? <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="border-b text-left text-muted-foreground"><tr><th className="py-2 pr-3">时间</th><th className="py-2 pr-3">来源</th><th className="py-2 pr-3">阶段</th><th className="py-2 pr-3">增长</th><th className="py-2 pr-3">通胀</th><th className="py-2 pr-3">置信度</th><th className="py-2">说明</th></tr></thead><tbody>{history.map((item) => <tr key={item.id} className="border-b last:border-0"><td className="whitespace-nowrap py-3 pr-3">{formatTime(item.observed_at)}</td><td className="py-3 pr-3">{item.source_type === 'manual' ? '人工' : '自动'}</td><td className="py-3 pr-3"><Badge variant="outline" className={phaseMeta[item.cycle_phase].tone}>{phaseMeta[item.cycle_phase].label}</Badge></td><td className="py-3 pr-3">{item.growth_score.toFixed(0)} · {trendLabel[item.growth_trend]}</td><td className="py-3 pr-3">{item.inflation_score.toFixed(0)} · {trendLabel[item.inflation_trend]}</td><td className="py-3 pr-3">{item.confidence.toFixed(0)}%</td><td className="py-3 text-muted-foreground">{item.summary || '-'}</td></tr>)}</tbody></table></div> : <div className="py-8 text-center text-sm text-muted-foreground">当前区域暂无历史记录</div>}</CardContent>
      </Card>
    </div>
  )
}

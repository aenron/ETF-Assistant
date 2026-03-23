import { useEffect, useState } from 'react'
import { adviceApi, type AdviceLogResponse } from '@/services/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  Plus,
  ArrowDownRight,
  Bot,
  Clock,
  BarChart3,
  WalletCards,
} from 'lucide-react'

const adviceTypeConfig: Record<string, { label: string; color: string; bgColor: string; icon: typeof TrendingUp }> = {
  buy: { label: '买入', color: 'text-red-600', bgColor: 'bg-red-50 border-red-200', icon: TrendingUp },
  sell: { label: '卖出', color: 'text-green-600', bgColor: 'bg-green-50 border-green-200', icon: TrendingDown },
  hold: { label: '持有', color: 'text-blue-600', bgColor: 'bg-blue-50 border-blue-200', icon: Minus },
  add: { label: '加仓', color: 'text-orange-600', bgColor: 'bg-orange-50 border-orange-200', icon: Plus },
  reduce: { label: '减仓', color: 'text-yellow-600', bgColor: 'bg-yellow-50 border-yellow-200', icon: ArrowDownRight },
  account: { label: '账户分析', color: 'text-violet-700', bgColor: 'bg-violet-50 border-violet-200', icon: WalletCards },
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
  summary: string
  action: string
  why: string[]
  newsBasis: string[]
  policyBasis: string[]
}

type ParsedAccountAnalysis = {
  summary: string
  positionAdvice: string
  rebalanceAdvice: string
  riskLevel: string
  actions: string[]
}

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 80 ? 'bg-green-500' : value >= 60 ? 'bg-blue-500' : value >= 40 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="font-mono text-xs text-muted-foreground">{value?.toFixed(0)}%</span>
    </div>
  )
}

function formatBeijingTime(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    ? value
    : `${value.replace(' ', 'T')}Z`
  return new Date(normalized).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

function splitItems(value: string) {
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
      const label = match?.[1] || '周期'
      const adviceType = (match?.[2] || 'hold').trim().toLowerCase()
      const confidence = Number(match?.[3] || 0)
      const action = lines.find((line) => line.startsWith('动作：'))?.replace('动作：', '').trim() || '继续观察'
      const conclusion = lines.find((line) => line.startsWith('结论：'))?.replace('结论：', '').trim() || ''
      const signals = splitItems(lines.find((line) => line.startsWith('信号：'))?.replace('信号：', '').trim() || '')
      const risks = splitItems(lines.find((line) => line.startsWith('风险：'))?.replace('风险：', '').trim() || '')
      return { label, adviceType, action, confidence, conclusion, signals, risks }
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
    summary: lines.find((line) => line.startsWith('综合说明：'))?.replace('综合说明：', '').trim() || '',
    action: lines.find((line) => line.startsWith('执行动作：'))?.replace('执行动作：', '').trim() || '',
    why: splitItems(lines.find((line) => line.startsWith('关键依据：'))?.replace('关键依据：', '').trim() || ''),
    newsBasis: splitItems(lines.find((line) => line.startsWith('新闻依据：'))?.replace('新闻依据：', '').trim() || ''),
    policyBasis: splitItems(lines.find((line) => line.startsWith('政策依据：'))?.replace('政策依据：', '').trim() || ''),
  }
}

function parseAccountAnalysis(reason: string | null): ParsedAccountAnalysis | null {
  const text = reason || ''
  if (!text.includes('总体判断：') && !text.includes('仓位建议：') && !text.includes('调仓建议：')) {
    return null
  }

  const lines = text.split('\n').map((item) => item.trim()).filter(Boolean)
  const actions: string[] = []
  let inActions = false
  let summary = ''
  let positionAdvice = ''
  let rebalanceAdvice = ''
  let riskLevel = ''

  for (const line of lines) {
    if (line === '关键操作：') {
      inActions = true
      continue
    }
    if (inActions) {
      actions.push(line.replace(/^\d+\.\s*/, '').trim())
      continue
    }
    if (line.startsWith('总体判断：')) {
      summary = line.replace('总体判断：', '').trim()
    } else if (line.startsWith('仓位建议：')) {
      positionAdvice = line.replace('仓位建议：', '').trim()
    } else if (line.startsWith('调仓建议：')) {
      rebalanceAdvice = line.replace('调仓建议：', '').trim()
    } else if (line.startsWith('风险等级：')) {
      riskLevel = line.replace('风险等级：', '').trim()
    }
  }

  return {
    summary,
    positionAdvice,
    rebalanceAdvice,
    riskLevel,
    actions,
  }
}

function AccountAnalysisPanel({ analysis }: { analysis: ParsedAccountAnalysis }) {
  const riskTone = analysis.riskLevel === 'high'
    ? 'border-red-200 bg-red-50 text-red-700'
    : analysis.riskLevel === 'low'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : 'border-amber-200 bg-amber-50 text-amber-700'

  return (
    <div className="space-y-3">
      <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
        <div className="text-xs font-medium text-muted-foreground">总体判断</div>
        <p className="mt-2 text-sm leading-relaxed">{analysis.summary || '暂无总体判断'}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
          <div className="text-xs font-medium text-muted-foreground">仓位建议</div>
          <p className="mt-2 text-sm leading-relaxed">{analysis.positionAdvice || '暂无仓位建议'}</p>
        </div>
        <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-muted-foreground">风险等级</span>
            <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${riskTone}`}>{analysis.riskLevel || 'medium'}</span>
          </div>
          <p className="mt-2 text-sm leading-relaxed">{analysis.rebalanceAdvice || '暂无调仓建议'}</p>
        </div>
      </div>
      <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
        <div className="mb-2 text-xs font-medium text-muted-foreground">关键操作</div>
        <div className="space-y-2">
          {analysis.actions.length > 0 ? analysis.actions.map((action, index) => (
            <div key={`${action}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm text-foreground/85">
              {index + 1}. {action}
            </div>
          )) : <span className="text-xs text-muted-foreground">暂无具体操作建议</span>}
        </div>
      </div>
    </div>
  )
}

function PlainReasonBlock({ reason }: { reason: string | null }) {
  const lines = (reason || '').split('\n').map((line) => line.trim()).filter(Boolean)
  return (
    <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
      <div className="space-y-2 text-sm leading-relaxed text-foreground/80">
        {lines.length > 0 ? lines.map((line, index) => <p key={`${line}-${index}`}>{line}</p>) : <p>-</p>}
      </div>
    </div>
  )
}

function HistoryReasonContent({ log }: { log: AdviceLogResponse }) {
  if (log.advice_type === 'account') {
    const analysis = parseAccountAnalysis(log.reason)
    if (analysis) {
      return <AccountAnalysisPanel analysis={analysis} />
    }
  }

  const periods = parseMultiHorizonReason(log.reason)
  const summary = parseDecisionSummary(log.reason)
  if (periods.length > 0) {
    const short = periods.find((item) => item.label === '短期')
    const long = periods.find((item) => item.label === '长期')
    return (
      <div className="space-y-3">
        <div className="rounded-xl border bg-primary/5 p-4">
          <div className="text-xs font-medium text-muted-foreground">主建议</div>
          <p className="mt-2 text-sm leading-relaxed">
            {summary?.mainJudgment || `中期以${(adviceTypeConfig[log.advice_type || 'hold'] || adviceTypeConfig.hold).label}为主，${periods.find((item) => item.label === '中期')?.conclusion || '延续中期判断'}`}
          </p>
          {summary?.summary ? (
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              {summary.summary}
            </p>
          ) : (
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              执行动作：{summary?.action || log.advice_type || 'hold'}。短期偏{periods.find((item) => item.label === '短期')?.conclusion || '短线节奏'}；
              长期看{periods.find((item) => item.label === '长期')?.conclusion || '长期配置价值'}
            </p>
          )}
          {(summary?.why.length || summary?.newsBasis.length || summary?.policyBasis.length) ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {summary.why.slice(0, 3).map((item, index) => (
                <span key={`why-${index}`} className="rounded-full border bg-background px-2.5 py-1 text-xs text-foreground/80">{item}</span>
              ))}
              {summary.newsBasis[0] && (
                <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800">新闻：{summary.newsBasis[0]}</span>
              )}
              {summary.policyBasis[0] && (
                <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs text-violet-800">政策：{summary.policyBasis[0]}</span>
              )}
            </div>
          ) : null}
        </div>
        <div className="rounded-xl border bg-white/70 p-4 shadow-sm">
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

  return <PlainReasonBlock reason={log.reason} />
}

export function AdvicePage() {
  const [logs, setLogs] = useState<AdviceLogResponse[]>([])
  const [loading, setLoading] = useState(true)

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const res = await adviceApi.getHistory(100)
      setLogs(res.data)
    } catch (error) {
      console.error('Failed to fetch logs:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold sm:text-3xl">决策历史</h1>
        <Button variant="outline" size="icon" onClick={fetchLogs} disabled={loading} className="w-full sm:w-10">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <div className="space-y-4">
        {logs.map((log) => {
          const config = adviceTypeConfig[log.advice_type || 'hold'] || adviceTypeConfig.hold
          const Icon = config.icon
          return (
            <Card key={log.id} className={`border ${config.bgColor} transition-shadow hover:shadow-md`}>
              <CardContent className="space-y-4 py-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-lg font-semibold">
                      {log.advice_type === 'account' ? 'ACCOUNT' : (log.etf_code || '-')}
                    </span>
                    {log.etf_name && <span className="text-sm text-muted-foreground">{log.etf_name}</span>}
                    <Badge variant="outline" className={`${config.color} border-current font-medium`}>
                      <Icon className="mr-1 h-3 w-3" />
                      {config.label}
                    </Badge>
                    <div className="flex items-center gap-1">
                      <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
                      <ConfidenceBar value={log.confidence || 0} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {formatBeijingTime(log.created_at)}
                  </div>
                </div>

                <HistoryReasonContent log={log} />

                {(log.llm_provider || log.llm_model) && (
                  <div className="flex items-center gap-1.5 border-t border-border/50 pt-1">
                    <Bot className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                      {log.llm_provider && <span className="font-medium">{log.llm_provider}</span>}
                      {log.llm_model && <span className="ml-1 opacity-75">({log.llm_model})</span>}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
        {logs.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              暂无历史建议记录
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

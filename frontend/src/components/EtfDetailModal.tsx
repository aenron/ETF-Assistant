import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { X, BarChart3, Activity, Calendar, Lightbulb, Loader2, RefreshCw, Clock } from 'lucide-react'
import {
  marketApi, adviceApi,
  type PortfolioWithMarket, type MarketHistoryResponse, type AdviceResponse, type AdviceLogResponse
} from '@/services/api'
import {
  ResponsiveContainer, ComposedChart, Line, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Area, ReferenceLine
} from 'recharts'

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

export function EtfDetailModal({ portfolio: p, onClose }: EtfDetailModalProps) {
  const [activeTab, setActiveTab] = useState<'chart' | 'advice'>('chart')
  const [historyData, setHistoryData] = useState<MarketHistoryResponse | null>(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [advice, setAdvice] = useState<AdviceResponse | null>(null)
  const [adviceLoading, setAdviceLoading] = useState(false)
  const [latestAdvice, setLatestAdvice] = useState<AdviceLogResponse | null>(null)
  const [latestLoading, setLatestLoading] = useState(true)

  useEffect(() => {
    fetchHistory()
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
    open: k.open_price,
    close: k.close_price,
    high: k.high_price,
    low: k.low_price,
    volume: k.volume,
    change: k.change_pct,
  }))

  const displayAdvice = advice || latestAdvice
  const displayConfig = displayAdvice ? (adviceTypeConfig[displayAdvice.advice_type || 'hold'] || adviceTypeConfig.hold) : null
  const displayConfidence = displayAdvice ? (displayAdvice.confidence || 0) : 0
  const displayTime = advice ? null : (latestAdvice?.created_at || null)

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
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {activeTab === 'chart' && (
            <>
              {/* K线图 */}
              <Card>
                <CardContent className="pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-semibold">近60日走势</h3>
                    <Button size="sm" variant="ghost" onClick={fetchHistory} disabled={historyLoading}>
                      <RefreshCw className={`h-3.5 w-3.5 mr-1 ${historyLoading ? 'animate-spin' : ''}`} />
                      刷新
                    </Button>
                  </div>
                  {historyLoading ? (
                    <div className="h-64 flex items-center justify-center text-muted-foreground">
                      <Loader2 className="h-6 w-6 animate-spin mr-2" />
                      加载中...
                    </div>
                  ) : chartData.length > 0 ? (
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                          <XAxis dataKey="date" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                          <YAxis
                            yAxisId="price"
                            domain={['auto', 'auto']}
                            tick={{ fontSize: 11 }}
                            width={55}
                          />
                          <YAxis yAxisId="volume" orientation="right" hide />
                          <Tooltip
                            contentStyle={{ fontSize: 12 }}
                            formatter={(value: number, name: string) => {
                              const labels: Record<string, string> = { close: '收盘', open: '开盘', high: '最高', low: '最低' }
                              return [value.toFixed(3), labels[name] || name]
                            }}
                          />
                          <Bar yAxisId="volume" dataKey="volume" fill="#e0e7ff" opacity={0.5} />
                          <Area yAxisId="price" type="monotone" dataKey="low" stroke="none" fill="#dcfce7" opacity={0.3} />
                          <Line yAxisId="price" type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={1.5} dot={false} />
                          {p.cost_price > 0 && (
                            <ReferenceLine yAxisId="price" y={p.cost_price} stroke="#f59e0b" strokeDasharray="5 5" label={{ value: `成本 ${p.cost_price.toFixed(3)}`, position: 'right', fontSize: 10, fill: '#f59e0b' }} />
                          )}
                        </ComposedChart>
                      </ResponsiveContainer>
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
                            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                              执行动作：{displayAdvice.action || displayAdvice.advice_type}。短期偏{displayAdvice.short_term.conclusion}；长期看{displayAdvice.long_term.conclusion}
                            </p>
                          </div>
                          {(displayAdvice.why.length > 0 || displayAdvice.news_basis.length > 0 || displayAdvice.policy_basis.length > 0) && (
                            <div className="rounded-xl border bg-background/60 p-4">
                              <div className="text-xs font-medium text-muted-foreground">依据摘要</div>
                              <div className="mt-2 flex flex-wrap gap-2">
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
                            </div>
                          )}
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
                        决策时间: {displayTime
                          ? new Date(displayTime).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
                          : new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
                        }
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
        </div>
      </div>
    </div>
  )
}

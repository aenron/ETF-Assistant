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
                      <h4 className="text-sm font-medium text-muted-foreground mb-2">分析理由</h4>
                      <p className="text-sm leading-relaxed">{displayAdvice.reason || '-'}</p>
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

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { portfolioApi, marketApi, adviceApi, type PortfolioWithMarket, type EtfSearchResult, type AdviceResponse, type AdviceLogResponse } from '@/services/api'
import { Plus, Pencil, Trash2, Search, TrendingUp, TrendingDown, Lightbulb, X, RefreshCw, Eye, Clock } from 'lucide-react'
import { EtfDetailModal } from './EtfDetailModal'
import { ConfirmDialog } from './ConfirmDialog'

interface PortfolioTableProps {
  portfolios: PortfolioWithMarket[]
  onRefresh: () => void
}

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
  })
  const [adviceLoading, setAdviceLoading] = useState<number | null>(null)
  const [currentAdvice, setCurrentAdvice] = useState<AdviceResponse | null>(null)
  const [showAdviceModal, setShowAdviceModal] = useState(false)
  const [refreshingCode, setRefreshingCode] = useState<string | null>(null)
  const [detailPortfolio, setDetailPortfolio] = useState<PortfolioWithMarket | null>(null)
  const [latestAdvices, setLatestAdvices] = useState<Record<string, AdviceLogResponse>>({})
  const [deleteTarget, setDeleteTarget] = useState<PortfolioWithMarket | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    fetchLatestAdvices()
  }, [])

  const fetchLatestAdvices = async () => {
    try {
      const res = await adviceApi.getLatest()
      setLatestAdvices(res.data || {})
    } catch (e) {
      console.error('Failed to fetch latest advices:', e)
    }
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

  const handleSubmit = async () => {
    const data = {
      etf_code: formData.etf_code,
      shares: parseFloat(formData.shares),
      cost_price: parseFloat(formData.cost_price),
      buy_date: formData.buy_date || undefined,
      note: formData.note || undefined,
    }

    if (editingId) {
      await portfolioApi.update(editingId, data)
    } else {
      await portfolioApi.create(data)
    }

    setShowForm(false)
    setEditingId(null)
    setFormData({ etf_code: '', shares: '', cost_price: '', buy_date: '', note: '' })
    onRefresh()
  }

  const handleEdit = (p: PortfolioWithMarket) => {
    setEditingId(p.id)
    setFormData({
      etf_code: p.etf_code,
      shares: p.shares.toString(),
      cost_price: p.cost_price.toString(),
      buy_date: p.buy_date || '',
      note: p.note || '',
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

  const handleGetAdvice = async (portfolioId: number) => {
    setAdviceLoading(portfolioId)
    try {
      const res = await adviceApi.generateForPortfolio(portfolioId)
      setCurrentAdvice(res.data)
      setShowAdviceModal(true)
      // 刷新最新建议
      fetchLatestAdvices()
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
    if (!value) return '未缓存'
    return new Date(value).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <CardTitle>持仓列表</CardTitle>
        <Button className="w-full sm:w-auto" onClick={() => { setShowForm(true); setEditingId(null); setFormData({ etf_code: '', shares: '', cost_price: '', buy_date: '', note: '' }); }}>
          <Plus className="h-4 w-4 mr-2" />
          新增持仓
        </Button>
      </CardHeader>
      <CardContent>
        {showForm && (
          <div className="mb-6 p-4 border rounded-lg bg-muted/50">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <div className="relative">
                <label className="text-sm font-medium">ETF代码</label>
                <div className="flex gap-2">
                  <Input
                    value={formData.etf_code}
                    onChange={(e) => setFormData({ ...formData, etf_code: e.target.value })}
                    placeholder="输入代码搜索"
                  />
                  <Button size="icon" variant="outline" onClick={handleSearch}>
                    <Search className="h-4 w-4" />
                  </Button>
                </div>
                {searchResults.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full bg-background border rounded-md shadow-lg max-h-48 overflow-auto">
                    {searchResults.map((etf) => (
                      <div
                        key={etf.code}
                        className="px-3 py-2 hover:bg-muted cursor-pointer"
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
                <label className="text-sm font-medium">备注</label>
                <Input
                  value={formData.note}
                  onChange={(e) => setFormData({ ...formData, note: e.target.value })}
                  placeholder="备注"
                />
              </div>
            </div>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              <Button className="w-full sm:w-auto" onClick={handleSubmit}>{editingId ? '更新' : '创建'}</Button>
              <Button className="w-full sm:w-auto" variant="outline" onClick={() => { setShowForm(false); setEditingId(null); }}>取消</Button>
            </div>
          </div>
        )}

        <div className="space-y-3 md:hidden">
          {portfolios.map((p) => {
            const latestAdvice = latestAdvices[p.etf_code]
            return (
              <div key={p.id} className="rounded-xl border bg-background p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-base font-semibold">{p.etf_code}</div>
                    <div className="mt-1 text-sm text-muted-foreground">{p.etf_name || '-'}</div>
                  </div>
                  {latestAdvice ? (
                    <Badge
                      variant="outline"
                      className={`shrink-0 text-xs ${getAdviceTypeColor(latestAdvice.advice_type || 'hold')} border-current`}
                    >
                      {getAdviceTypeLabel(latestAdvice.advice_type || 'hold')}
                    </Badge>
                  ) : (
                    <span className="shrink-0 text-xs text-muted-foreground">暂无建议</span>
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
                    <div className={`${p.pnl_pct && p.pnl_pct > 0 ? 'text-red-500' : p.pnl_pct && p.pnl_pct < 0 ? 'text-green-500' : ''} mt-1 font-medium`}>
                      {p.pnl_pct ? `${p.pnl_pct.toFixed(2)}%` : '-'}
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
                <th className="text-right py-3 px-2">份额</th>
                <th className="text-right py-3 px-2">成本价</th>
                <th className="text-right py-3 px-2">现价</th>
                <th className="text-right py-3 px-2">市值</th>
                <th className="text-right py-3 px-2">盈亏</th>
                <th className="text-right py-3 px-2">涨跌</th>
                <th className="text-center py-3 px-2">AI建议</th>
                <th className="text-center py-3 px-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {portfolios.map((p) => {
                const latestAdvice = latestAdvices[p.etf_code]
                return (
                <tr key={p.id} className="border-b hover:bg-muted/50 cursor-pointer" onClick={() => setDetailPortfolio(p)}>
                  <td className="py-3 px-2 font-mono">{p.etf_code}</td>
                  <td className="py-3 px-2">{p.etf_name || '-'}</td>
                  <td className="py-3 px-2 text-right">{p.shares.toLocaleString()}</td>
                  <td className="py-3 px-2 text-right">{p.cost_price.toFixed(4)}</td>
                  <td className="py-3 px-2 text-right">
                    <div className="flex flex-col items-end">
                      <span>{p.current_price?.toFixed(3) || '-'}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {formatMarketRefreshedAt(p.market_refreshed_at)}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 px-2 text-right">{p.market_value?.toFixed(2) || '-'}</td>
                  <td className={`py-3 px-2 text-right ${p.pnl_pct && p.pnl_pct > 0 ? 'text-red-500' : p.pnl_pct && p.pnl_pct < 0 ? 'text-green-500' : ''}`}>
                    {p.pnl_pct ? `${p.pnl_pct.toFixed(2)}%` : '-'}
                  </td>
                  <td className={`py-3 px-2 text-right ${p.change_pct && p.change_pct > 0 ? 'text-red-500' : p.change_pct && p.change_pct < 0 ? 'text-green-500' : ''}`}>
                    {p.change_pct ? (
                      <span className="flex items-center justify-end">
                        {p.change_pct > 0 ? <TrendingUp className="h-3 w-3 mr-1" /> : <TrendingDown className="h-3 w-3 mr-1" />}
                        {p.change_pct.toFixed(2)}%
                      </span>
                    ) : '-'}
                  </td>
                  <td className="py-3 px-2 text-center" onClick={e => e.stopPropagation()}>
                    {latestAdvice ? (
                      <div className="flex flex-col items-center gap-0.5">
                        <Badge
                          variant="outline"
                          className={`text-xs ${getAdviceTypeColor(latestAdvice.advice_type || 'hold')} border-current`}
                        >
                          {getAdviceTypeLabel(latestAdvice.advice_type || 'hold')}
                          <span className="ml-1 opacity-70">{latestAdvice.confidence?.toFixed(0)}%</span>
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          {new Date(latestAdvice.created_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">暂无</span>
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
        {showAdviceModal && currentAdvice && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-background rounded-lg p-6 max-w-3xl w-full mx-4 shadow-xl">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">投资建议</h3>
                <Button size="icon" variant="ghost" onClick={() => setShowAdviceModal(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-lg">{currentAdvice.etf_code}</span>
                  <span className="text-muted-foreground">{currentAdvice.etf_name}</span>
                </div>

                {/* 顶部操作栏 - 匹配 EtfDetailModal 样式 */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
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
                    <RefreshCw className="h-3.5 w-3.5 mr-1" />
                    重新分析
                  </Button>
                </div>

                {/* 多周期建议 */}
                <div>
                  <h4 className="text-sm font-medium text-muted-foreground mb-2">多周期建议</h4>
                  <div className="space-y-3">
                    {/* 主建议区块 */}
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

                    {/* 补充判断区块 */}
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

                {/* 价格和盈亏 */}
                {currentAdvice.current_price && (
                  <div className="text-sm text-muted-foreground">
                    当前价格: {currentAdvice.current_price.toFixed(3)} |
                    盈亏: {currentAdvice.pnl_pct?.toFixed(2)}%
                  </div>
                )}

                {/* 决策时间 */}
                <div className="flex items-center gap-1.5 pt-2 border-t text-xs text-muted-foreground">
                  <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>
                    决策时间: {new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
                  </span>
                </div>
              </div>

              <div className="mt-6 flex justify-end">
                <Button onClick={() => setShowAdviceModal(false)}>关闭</Button>
              </div>
            </div>
          </div>
        )}

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

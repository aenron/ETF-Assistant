import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { portfolioApi, marketApi, adviceApi, type PortfolioWithMarket, type EtfSearchResult, type AdviceResponse } from '@/services/api'
import { Plus, Pencil, Trash2, Search, TrendingUp, TrendingDown, Lightbulb, X } from 'lucide-react'

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

  const handleDelete = async (id: number) => {
    if (confirm('确定删除该持仓？')) {
      await portfolioApi.delete(id)
      onRefresh()
    }
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

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>持仓列表</CardTitle>
        <Button onClick={() => { setShowForm(true); setEditingId(null); setFormData({ etf_code: '', shares: '', cost_price: '', buy_date: '', note: '' }); }}>
          <Plus className="h-4 w-4 mr-2" />
          新增持仓
        </Button>
      </CardHeader>
      <CardContent>
        {showForm && (
          <div className="mb-6 p-4 border rounded-lg bg-muted/50">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
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
            <div className="mt-4 flex gap-2">
              <Button onClick={handleSubmit}>{editingId ? '更新' : '创建'}</Button>
              <Button variant="outline" onClick={() => { setShowForm(false); setEditingId(null); }}>取消</Button>
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
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
                <th className="text-center py-3 px-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {portfolios.map((p) => (
                <tr key={p.id} className="border-b hover:bg-muted/50">
                  <td className="py-3 px-2 font-mono">{p.etf_code}</td>
                  <td className="py-3 px-2">{p.etf_name || '-'}</td>
                  <td className="py-3 px-2 text-right">{p.shares.toLocaleString()}</td>
                  <td className="py-3 px-2 text-right">{p.cost_price.toFixed(4)}</td>
                  <td className="py-3 px-2 text-right">{p.current_price?.toFixed(3) || '-'}</td>
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
                  <td className="py-3 px-2 text-center">
                    <Button 
                      size="icon" 
                      variant="ghost" 
                      onClick={() => handleGetAdvice(p.id)}
                      disabled={adviceLoading === p.id}
                      title="获取建议"
                    >
                      <Lightbulb className={`h-4 w-4 ${adviceLoading === p.id ? 'animate-pulse text-yellow-500' : ''}`} />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => handleEdit(p)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button size="icon" variant="ghost" onClick={() => handleDelete(p.id)}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </td>
                </tr>
              ))}
              {portfolios.length === 0 && (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-muted-foreground">
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
            <div className="bg-background rounded-lg p-6 max-w-md w-full mx-4 shadow-xl">
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
                
                <div className="flex items-center gap-4">
                  <div>
                    <span className="text-sm text-muted-foreground">建议操作</span>
                    <div className={`text-xl font-bold ${getAdviceTypeColor(currentAdvice.advice_type)}`}>
                      {getAdviceTypeLabel(currentAdvice.advice_type)}
                    </div>
                  </div>
                  <div>
                    <span className="text-sm text-muted-foreground">置信度</span>
                    <div className="text-xl font-bold">{currentAdvice.confidence}%</div>
                  </div>
                </div>
                
                <div>
                  <span className="text-sm text-muted-foreground">分析理由</span>
                  <p className="mt-1 text-sm leading-relaxed">{currentAdvice.reason}</p>
                </div>
                
                {currentAdvice.current_price && (
                  <div className="text-sm text-muted-foreground">
                    当前价格: {currentAdvice.current_price.toFixed(3)} | 
                    盈亏: {currentAdvice.pnl_pct?.toFixed(2)}%
                  </div>
                )}
              </div>
              
              <div className="mt-6 flex justify-end">
                <Button onClick={() => setShowAdviceModal(false)}>关闭</Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

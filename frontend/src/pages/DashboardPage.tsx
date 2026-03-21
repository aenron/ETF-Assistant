import { useEffect, useState } from 'react'
import { portfolioApi, adviceApi, marketApi, type PortfolioSummary } from '@/services/api'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { AdviceCard } from '@/components/AdviceCard'
import { Button } from '@/components/ui/button'
import { RefreshCw, Sparkles, AlertCircle, TrendingUp } from 'lucide-react'
import type { AdviceResponse } from '@/services/api'

export function DashboardPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [advices, setAdvices] = useState<AdviceResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await portfolioApi.getSummary()
      setSummary(res.data)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleRefreshMarket = async () => {
    setRefreshing(true)
    try {
      const res = await marketApi.refreshAll()
      if (res.data.success) {
        // 刷新后重新获取数据
        await fetchData()
        alert(res.data.message || '行情刷新成功')
      } else {
        alert(res.data.message || '刷新失败')
      }
    } catch (error) {
      console.error('Failed to refresh market:', error)
      alert('刷新行情失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleGenerateAdvice = async () => {
    setGenerating(true)
    try {
      const res = await adviceApi.generate()
      setAdvices(res.data)
    } catch (error) {
      console.error('Failed to generate advice:', error)
      alert('生成建议失败，请检查LLM配置')
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">投资仪表盘</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button variant="outline" onClick={handleRefreshMarket} disabled={refreshing}>
            <TrendingUp className="h-4 w-4 mr-2" />
            {refreshing ? '刷新中...' : '刷新行情'}
          </Button>
          <Button onClick={handleGenerateAdvice} disabled={generating}>
            <Sparkles className="h-4 w-4 mr-2" />
            {generating ? '生成中...' : '生成投资建议'}
          </Button>
        </div>
      </div>

      <PortfolioSummaryCard summary={summary} />

      {advices.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">智能决策建议</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {advices.map((advice) => (
              <AdviceCard key={advice.etf_code} advice={advice} />
            ))}
          </div>
        </div>
      )}

      {advices.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <AlertCircle className="h-12 w-12 mb-4" />
          <p>点击"生成投资建议"获取AI分析</p>
        </div>
      )}
    </div>
  )
}

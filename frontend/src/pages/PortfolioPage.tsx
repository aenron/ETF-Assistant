import { useEffect, useState } from 'react'
import { portfolioApi, marketApi, type PortfolioWithMarket, type PortfolioSummary } from '@/services/api'
import { PortfolioTable } from '@/components/PortfolioTable'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { RefreshCw, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      // 检查当前用户
      const userStr = localStorage.getItem('etf_user')
      console.log('Current user from localStorage:', userStr)
      
      const [pRes, sRes] = await Promise.all([
        portfolioApi.getList(),
        portfolioApi.getSummary(),
      ])
      console.log('Portfolio data:', pRes.data, 'Length:', pRes.data?.length)
      console.log('Summary data:', sRes.data)
      setPortfolios(pRes.data)
      setSummary(sRes.data)
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

  useEffect(() => {
    fetchData()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">持仓管理</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button variant="outline" onClick={handleRefreshMarket} disabled={refreshing}>
            <TrendingUp className="h-4 w-4 mr-2" />
            {refreshing ? '刷新中...' : '刷新行情'}
          </Button>
        </div>
      </div>

      <PortfolioSummaryCard summary={summary} />
      <PortfolioTable portfolios={portfolios} onRefresh={fetchData} />
    </div>
  )
}

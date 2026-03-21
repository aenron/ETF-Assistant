import { useEffect, useState } from 'react'
import { portfolioApi, type PortfolioWithMarket, type PortfolioSummary } from '@/services/api'
import { PortfolioTable } from '@/components/PortfolioTable'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    setLoading(true)
    try {
      const [pRes, sRes] = await Promise.all([
        portfolioApi.getList(),
        portfolioApi.getSummary(),
      ])
      setPortfolios(pRes.data)
      setSummary(sRes.data)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">持仓管理</h1>
        <Button variant="outline" size="icon" onClick={fetchData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <PortfolioSummaryCard summary={summary} />
      <PortfolioTable portfolios={portfolios} onRefresh={fetchData} />
    </div>
  )
}

import { useEffect, useState } from 'react'
import {
  portfolioApi,
  adviceApi,
  marketApi,
  type PortfolioSummary,
  type PortfolioWithMarket,
  type AccountAnalysisResponse,
} from '@/services/api'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { AccountAnalysisCard } from '@/components/AccountAnalysisCard'
import { Button } from '@/components/ui/button'
import { RefreshCw, Sparkles, TrendingUp } from 'lucide-react'
import { authApi } from '@/services/authApi'
import { compareBeijingTimeDesc, formatBeijingTime } from '@/utils/time'

export function DashboardPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])
  const [accountAnalysis, setAccountAnalysis] = useState<AccountAnalysisResponse | null>(null)
  const [accountBalance, setAccountBalance] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [analyzingAccount, setAnalyzingAccount] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [marketRefreshAt, setMarketRefreshAt] = useState<string | null>(null)

  const formatMarketRefreshAt = (value: string | null) =>
    formatBeijingTime(value, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }, '暂无缓存行情')

  const fetchData = async () => {
    setLoading(true)
    try {
      const [summaryRes, balanceRes, portfolioRes] = await Promise.all([
        portfolioApi.getSummary(),
        authApi.getAccountBalance(),
        portfolioApi.getList(),
      ])
      setSummary(summaryRes.data)
      setAccountBalance(balanceRes.account_balance ?? undefined)
      setPortfolios(portfolioRes.data)
      const latestRefreshAt = portfolioRes.data
        .map((portfolio: PortfolioWithMarket) => portfolio.market_refreshed_at)
        .filter((value): value is string => Boolean(value))
        .sort(compareBeijingTimeDesc)
        .at(0) ?? null
      setMarketRefreshAt(latestRefreshAt)
    } catch (error) {
      console.error('Failed to fetch market refresh time:', error)
    }
  }

  const fetchLatestAccountAnalysis = async () => {
    try {
      const res = await adviceApi.getLatestAccountAnalysis()
      setAccountAnalysis(res.data)
    } catch (error) {
      console.error('Failed to fetch latest account analysis:', error)
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

  const handleAnalyzeAccount = async () => {
    setAnalyzingAccount(true)
    try {
      const res = await adviceApi.analyzeAccount()
      setAccountAnalysis(res.data)
    } catch (error) {
      console.error('Failed to analyze account:', error)
      alert('账户分析失败，请检查LLM配置')
    } finally {
      setAnalyzingAccount(false)
    }
  }

  useEffect(() => {
    fetchData()
    fetchLatestAccountAnalysis()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">投资仪表盘</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            当前使用行情时间：{formatMarketRefreshAt(marketRefreshAt)}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[auto,1fr,1fr] lg:flex">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} className="w-full sm:w-10">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button variant="outline" onClick={handleRefreshMarket} disabled={refreshing} className="w-full">
            <TrendingUp className="h-4 w-4 mr-2" />
            {refreshing ? '刷新中...' : '刷新行情'}
          </Button>
          <Button variant="outline" onClick={handleAnalyzeAccount} disabled={analyzingAccount} className="w-full">
            <Sparkles className="h-4 w-4 mr-2" />
            {analyzingAccount ? '分析中...' : '分析账户'}
          </Button>
        </div>
      </div>

      <PortfolioSummaryCard
        summary={summary}
        portfolios={portfolios}
        accountBalance={accountBalance}
        onAccountBalanceChange={setAccountBalance}
        showPnlAttribution
      />

      {accountAnalysis && <AccountAnalysisCard analysis={accountAnalysis} />}

    </div>
  )
}

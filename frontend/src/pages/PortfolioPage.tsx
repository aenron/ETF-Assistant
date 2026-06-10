import { useEffect, useState } from 'react'
import {
  portfolioApi,
  marketApi,
  adviceApi,
  type PortfolioWithMarket,
  type PortfolioSummary,
} from '@/services/api'
import { PortfolioTable } from '@/components/PortfolioTable'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { RefreshCw, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { authApi } from '@/services/authApi'
import { compareBeijingTimeDesc, formatBeijingTime } from '@/utils/time'

export function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [accountBalance, setAccountBalance] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [analyzingAll, setAnalyzingAll] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error' | 'neutral'>('neutral')

  const latestMarketRefreshAt = portfolios
    .map((portfolio) => portfolio.market_refreshed_at)
    .filter((value): value is string => Boolean(value))
    .sort(compareBeijingTimeDesc)
    .at(0) ?? null
  const missingQuoteCount = summary?.missing_quote_count ?? portfolios.filter((portfolio) => portfolio.current_price == null).length

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
      // 检查当前用户
      const userStr = localStorage.getItem('etf_user')
      console.log('Current user from localStorage:', userStr)
      
      const [pRes, sRes, balanceRes] = await Promise.all([
        portfolioApi.getList(),
        portfolioApi.getSummary(),
        authApi.getAccountBalance(),
      ])
      console.log('Portfolio data:', pRes.data, 'Length:', pRes.data?.length)
      console.log('Summary data:', sRes.data)
      setPortfolios(pRes.data)
      setSummary(sRes.data)
      setAccountBalance(balanceRes.account_balance ?? undefined)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleAnalyzeAll = async () => {
    if (portfolios.length === 0) {
      setMessageTone('neutral')
      setMessage('当前没有可分析的持仓')
      return
    }
    setAnalyzingAll(true)
    setMessageTone('neutral')
    setMessage('正在生成账户分析...')
    try {
      const codes = portfolios.map((p) => p.etf_code)
      await adviceApi.generate(codes)
      setMessageTone('success')
      setMessage('一键分析任务已完成，最新建议已缓存，可前往决策历史查看')
      await fetchData()
    } catch (error) {
      console.error('Failed to analyze all portfolios:', error)
      setMessageTone('error')
      setMessage('一键分析失败，请稍后重试')
    } finally {
      setAnalyzingAll(false)
    }
  }

  const handleRefreshMarket = async () => {
    setRefreshing(true)
    setMessageTone('neutral')
    setMessage('正在刷新行情缓存...')
    try {
      const res = await marketApi.refreshAll()
      if (res.data.success) {
        await fetchData()
        setMessageTone('success')
        setMessage(res.data.message || '行情刷新成功')
      } else {
        setMessageTone('error')
        setMessage(res.data.message || '刷新失败')
      }
    } catch (error) {
      console.error('Failed to refresh market:', error)
      setMessageTone('error')
      setMessage('刷新行情失败')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const messageClassName = messageTone === 'success'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : messageTone === 'error'
      ? 'border-red-200 bg-red-50 text-red-700'
      : 'border-slate-200 bg-slate-50 text-slate-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">持仓管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            当前使用行情时间：{formatMarketRefreshAt(latestMarketRefreshAt)}
          </p>
          {portfolios.length > 0 && missingQuoteCount > 0 && (
            <p className="mt-1 text-sm text-amber-700">
              {missingQuoteCount} 个持仓暂无行情缓存，后台刷新完成后会自动显示价格、市值和盈亏。
            </p>
          )}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[auto,1fr,1fr] lg:flex">
          <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} className="w-full sm:w-10">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
          <Button variant="outline" onClick={handleRefreshMarket} disabled={refreshing} className="w-full">
            <TrendingUp className="h-4 w-4 mr-2" />
            {refreshing ? '刷新中...' : '刷新行情'}
          </Button>
          <Button variant="secondary" onClick={handleAnalyzeAll} disabled={analyzingAll} className="w-full">
            <TrendingUp className="h-4 w-4 mr-2" />
            {analyzingAll ? '分析中...' : '一键分析'}
          </Button>
        </div>
      </div>

      {message && <div className={`rounded-lg border px-4 py-3 text-sm ${messageClassName}`}>{message}</div>}

      <PortfolioSummaryCard
        summary={summary}
        accountBalance={accountBalance}
        onAccountBalanceChange={setAccountBalance}
        showPnlAttribution={false}
        showDistribution={false}
        showExposureAnalysis={false}
      />
      <PortfolioTable portfolios={portfolios} onRefresh={fetchData} />
    </div>
  )
}

import { useEffect, useState } from 'react'
import {
  portfolioApi,
  adviceApi,
  marketApi,
  type PortfolioSummary,
  type PortfolioWithMarket,
  type AccountAnalysisResponse,
  type PeriodAdvice,
} from '@/services/api'
import { PortfolioSummaryCard } from '@/components/PortfolioSummaryCard'
import { AdviceCard } from '@/components/AdviceCard'
import { AccountAnalysisCard } from '@/components/AccountAnalysisCard'
import { Button } from '@/components/ui/button'
import { RefreshCw, Sparkles, AlertCircle, TrendingUp } from 'lucide-react'
import type { AdviceResponse } from '@/services/api'
import { authApi } from '@/services/authApi'

export function DashboardPage() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [advices, setAdvices] = useState<AdviceResponse[]>([])
  const [accountAnalysis, setAccountAnalysis] = useState<AccountAnalysisResponse | null>(null)
  const [accountBalance, setAccountBalance] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [analyzingAccount, setAnalyzingAccount] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [marketRefreshAt, setMarketRefreshAt] = useState<string | null>(null)

  const formatMarketRefreshAt = (value: string | null) => {
    if (!value) return '暂无缓存行情'
    return new Date(value).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const fetchData = async () => {
    setLoading(true)
    try {
      const [summaryRes, balanceRes] = await Promise.all([
        portfolioApi.getSummary(),
        authApi.getAccountBalance(),
      ])
      setSummary(summaryRes.data)
      setAccountBalance(balanceRes.account_balance ?? undefined)
    } catch (error) {
      console.error('Failed to fetch data:', error)
    } finally {
      setLoading(false)
    }
  }

  // 获取缓存的最新建议
  const fetchLatestAdvice = async () => {
    try {
      const res = await adviceApi.getLatest()
      const adviceLogs = Object.values(res.data || {})
      
      // 获取用户持仓的实时行情
      const quotesRes = await portfolioApi.getList()
      const latestRefreshAt = quotesRes.data
        .map((portfolio: PortfolioWithMarket) => portfolio.market_refreshed_at)
        .filter((value): value is string => Boolean(value))
        .sort()
        .at(-1) ?? null
      setMarketRefreshAt(latestRefreshAt)
      const quotesMap = new Map(quotesRes.data.map((p: PortfolioWithMarket) => [p.etf_code, p]))
      
      // 将 Record<string, AdviceLogResponse> 转换为 AdviceResponse[]
      const latestAdvices: AdviceResponse[] = adviceLogs.map(log => {
        const portfolio = quotesMap.get(log.etf_code || '')
        const fallbackPeriod: PeriodAdvice = {
          advice_type: log.advice_type || 'hold',
          action: '继续观察',
          conclusion: log.reason || '',
          signals: [],
          risks: [],
          confidence: log.confidence || 0,
        }
        return {
          etf_code: log.etf_code || '',
          etf_name: portfolio?.etf_name ?? log.etf_name ?? null,
          advice_type: log.advice_type || 'hold',
          main_judgment: log.reason || '',
          action: log.advice_type || 'hold',
          why: [],
          news_basis: [],
          policy_basis: [],
          reason: log.reason || '',
          confidence: log.confidence || 0,
          short_term: fallbackPeriod,
          medium_term: fallbackPeriod,
          long_term: fallbackPeriod,
          current_price: portfolio?.current_price ?? null,
          pnl_pct: portfolio?.pnl_pct ?? null,
        }
      })
      setAdvices(latestAdvices)
    } catch (error) {
      console.error('Failed to fetch latest advice:', error)
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
        // 刷新后重新获取数据
        await Promise.all([fetchData(), fetchLatestAdvice()])
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
    fetchLatestAdvice()
    fetchLatestAccountAnalysis()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">投资仪表盘</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            当前使用行情时间：{formatMarketRefreshAt(marketRefreshAt)}
          </p>
        </div>
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
          <Button variant="outline" onClick={handleAnalyzeAccount} disabled={analyzingAccount}>
            <Sparkles className="h-4 w-4 mr-2" />
            {analyzingAccount ? '分析中...' : '分析账户'}
          </Button>
        </div>
      </div>

      <PortfolioSummaryCard
        summary={summary}
        accountBalance={accountBalance}
        onAccountBalanceChange={setAccountBalance}
      />

      {accountAnalysis && <AccountAnalysisCard analysis={accountAnalysis} />}

      {advices.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">智能决策建议</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {advices.map((advice) => (
              <AdviceCard key={advice.etf_code} advice={advice} accountBalance={accountBalance} />
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

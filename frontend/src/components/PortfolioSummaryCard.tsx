import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type PortfolioSummary } from '@/services/api'
import { TrendingUp, TrendingDown, Wallet, PieChart } from 'lucide-react'
import { PieChart as RechartsPie, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { AccountBalanceEditor } from '@/components/AccountBalanceEditor'

interface PortfolioSummaryCardProps {
  summary: PortfolioSummary | null
  accountBalance?: number | null
  onAccountBalanceChange?: (balance: number) => void
}

const CATEGORY_COLORS: Record<string, string> = {
  宽基指数: '#2563eb',
  红利策略: '#7c3aed',
  海外市场: '#0f766e',
  医药医疗: '#16a34a',
  半导体芯片: '#0891b2',
  'TMT/人工智能': '#0284c7',
  消费: '#ea580c',
  新能源: '#dc2626',
  金融地产: '#ca8a04',
  军工国防: '#475569',
  贵金属: '#b45309',
  能源化工: '#9a3412',
  农产品: '#65a30d',
  债券: '#64748b',
  现金管理: '#334155',
  REITs: '#c2410c',
  未分类: '#94a3b8',
}

export function PortfolioSummaryCard({
  summary,
  accountBalance,
  onAccountBalanceChange,
}: PortfolioSummaryCardProps) {
  if (!summary) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          加载中...
        </CardContent>
      </Card>
    )
  }

  const pieData = Object.entries(summary.category_distribution).map(([name, value]) => ({
    name,
    value: Number(value),
  }))
  const totalDistributionValue = pieData.reduce((sum, item) => sum + item.value, 0)
  const distributionData = pieData
    .sort((a, b) => b.value - a.value)
    .reduce<{ name: string; value: number; color: string }[]>((acc, item) => {
      const percent = totalDistributionValue > 0 ? item.value / totalDistributionValue * 100 : 0
      if (percent < 5) {
        const otherItem = acc.find((entry) => entry.name === '未分类')
        if (otherItem) {
          otherItem.value += item.value
        } else {
          acc.push({ name: '未分类', value: item.value, color: CATEGORY_COLORS.未分类 })
        }
      } else {
        acc.push({
          name: item.name,
          value: item.value,
          color: CATEGORY_COLORS[item.name] || CATEGORY_COLORS.未分类,
        })
      }
      return acc
    }, [])
  const topCategories = distributionData
    .slice()
    .sort((a, b) => b.value - a.value)
  const topTwoRatio = totalDistributionValue > 0
    ? topCategories.slice(0, 2).reduce((sum, item) => sum + item.value, 0) / totalDistributionValue * 100
    : 0
  const concentrationHint = topTwoRatio >= 60
    ? `前两大类占比 ${topTwoRatio.toFixed(1)}%，集中度偏高，建议关注单一赛道波动。`
    : topTwoRatio >= 40
      ? `前两大类占比 ${topTwoRatio.toFixed(1)}%，集中度中等，结构仍有优化空间。`
      : `前两大类占比 ${topTwoRatio.toFixed(1)}%，持仓分布相对均衡。`

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总市值</CardTitle>
          <Wallet className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">¥{summary.total_market_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">账户金额</CardTitle>
          <Wallet className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-2xl font-bold">
            {accountBalance !== null && accountBalance !== undefined
              ? `¥${accountBalance.toLocaleString(undefined, { minimumFractionDigits: 2 })}`
              : '-'}
          </div>
          <AccountBalanceEditor
            balance={accountBalance}
            onBalanceChange={onAccountBalanceChange}
            triggerClassName="w-full"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总成本</CardTitle>
          <PieChart className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">¥{summary.total_cost.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总盈亏</CardTitle>
          {summary.total_pnl >= 0 ? <TrendingUp className="h-4 w-4 text-red-500" /> : <TrendingDown className="h-4 w-4 text-green-500" />}
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${summary.total_pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>
            {summary.total_pnl >= 0 ? '+' : ''}{summary.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })} ({summary.total_pnl_pct.toFixed(2)}%)
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">今日盈亏</CardTitle>
          {(summary.today_pnl ?? 0) >= 0 ? <TrendingUp className="h-4 w-4 text-red-500" /> : <TrendingDown className="h-4 w-4 text-green-500" />}
        </CardHeader>
        <CardContent>
          <div className={`text-2xl font-bold ${(summary.today_pnl ?? 0) >= 0 ? 'text-red-500' : 'text-green-500'}`}>
            {summary.today_pnl !== null ? `${summary.today_pnl >= 0 ? '+' : ''}${summary.today_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : '-'}
          </div>
        </CardContent>
      </Card>

      {summary.total_cost === 0 && summary.total_market_value === 0 ? (
        <Card className="md:col-span-2 lg:col-span-5">
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground mb-4">暂无持仓数据</p>
            <p className="text-sm text-muted-foreground">请前往"持仓管理"添加ETF持仓</p>
          </CardContent>
        </Card>
      ) : null}

      {distributionData.length > 0 && (
        <Card className="md:col-span-2 lg:col-span-5">
          <CardHeader>
            <CardTitle className="text-sm font-medium">持仓分布</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-6 lg:grid-cols-[minmax(260px,320px)_1fr] lg:items-center">
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <RechartsPie>
                    <Pie
                      data={distributionData}
                      cx="50%"
                      cy="50%"
                      innerRadius={72}
                      outerRadius={104}
                      paddingAngle={2}
                      strokeWidth={0}
                      dataKey="value"
                    >
                      {distributionData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value: number) => `¥${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                    />
                  </RechartsPie>
                </ResponsiveContainer>
              </div>

              <div className="space-y-4">
                <div className="rounded-lg border bg-muted/20 p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">资产分类</div>
                  <div className="mt-2 text-2xl font-bold">
                    ¥{totalDistributionValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">{concentrationHint}</p>
                </div>

                <div className="space-y-3">
                  {topCategories.map((item) => {
                    const ratio = totalDistributionValue > 0 ? item.value / totalDistributionValue * 100 : 0
                    return (
                      <div key={item.name} className="space-y-2">
                        <div className="flex items-center justify-between gap-4">
                          <div className="flex items-center gap-2 text-sm font-medium">
                            <span
                              className="h-2.5 w-2.5 rounded-full"
                              style={{ backgroundColor: item.color }}
                            />
                            <span>{item.name}</span>
                          </div>
                          <div className="text-right">
                            <div className="text-sm font-medium">
                              ¥{item.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                            </div>
                            <div className="text-xs text-muted-foreground">{ratio.toFixed(1)}%</div>
                          </div>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{ width: `${ratio}%`, backgroundColor: item.color }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

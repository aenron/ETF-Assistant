import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type PortfolioSummary } from '@/services/api'
import { TrendingUp, TrendingDown, Wallet, PieChart } from 'lucide-react'
import { PieChart as RechartsPie, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts'

interface PortfolioSummaryCardProps {
  summary: PortfolioSummary | null
}

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16']

export function PortfolioSummaryCard({ summary }: PortfolioSummaryCardProps) {
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

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
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

      {pieData.length > 0 && (
        <Card className="md:col-span-2 lg:col-span-4">
          <CardHeader>
            <CardTitle className="text-sm font-medium">持仓分布</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsPie>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {pieData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => `¥${value.toLocaleString()}`} />
                </RechartsPie>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

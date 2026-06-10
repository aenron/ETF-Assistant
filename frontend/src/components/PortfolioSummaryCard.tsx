import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { type PortfolioSummary, type PortfolioWithMarket } from '@/services/api'
import { TrendingUp, TrendingDown, Wallet, PieChart } from 'lucide-react'
import { PieChart as RechartsPie, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { AccountBalanceEditor } from '@/components/AccountBalanceEditor'

interface PortfolioSummaryCardProps {
  summary: PortfolioSummary | null
  portfolios?: PortfolioWithMarket[]
  accountBalance?: number | null
  onAccountBalanceChange?: (balance: number) => void
  showPnlAttribution?: boolean
  showDistribution?: boolean
  showExposureAnalysis?: boolean
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

const PNL_COLORS = ['#2563eb', '#16a34a', '#ea580c', '#7c3aed', '#0891b2', '#dc2626', '#ca8a04', '#0f766e']

function formatCurrency(value: number) {
  return `¥${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}


function rebalanceStatusClass(status: string) {
  if (status === 'executable') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'blocked') return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'reduce') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'wait_signal') return 'border-sky-200 bg-sky-50 text-sky-700'
  return 'border-slate-200 bg-slate-50 text-slate-600'
}

function ExposureList({ title, items }: { title: string; items: Array<{ name: string; market_value: number; ratio: number }> }) {
  const visible = items.slice(0, 5)
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-3 space-y-3">
        {visible.length ? visible.map((item) => (
          <div key={`${title}-${item.name}`} className="space-y-1.5">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">{item.name}</span>
              <span className="text-muted-foreground">{item.ratio.toFixed(1)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, Math.max(0, item.ratio))}%` }} />
            </div>
            <div className="text-xs text-muted-foreground">{formatCurrency(item.market_value)}</div>
          </div>
        )) : <div className="text-sm text-muted-foreground">暂无数据</div>}
      </div>
    </div>
  )
}

function buildPnlAttributionData(
  portfolios: PortfolioWithMarket[],
  mode: 'total' | 'today',
) {
  const rawItems = portfolios
    .map((portfolio) => {
      const actualValue =
        mode === 'total'
          ? Number(portfolio.pnl ?? 0)
          : Number(portfolio.today_pnl ?? 0)
      return {
        key: `${portfolio.etf_code}-${mode}`,
        name: portfolio.etf_name || portfolio.etf_code,
        code: portfolio.etf_code,
        actualValue,
        value: Math.abs(actualValue),
      }
    })
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value)

  if (rawItems.length === 0) {
    return []
  }

  const totalAbsValue = rawItems.reduce((sum, item) => sum + item.value, 0)
  const topItems = rawItems.slice(0, 5)
  const otherItems = rawItems.slice(5)
  const result = topItems.map((item, index) => ({
    ...item,
    color: PNL_COLORS[index % PNL_COLORS.length],
    ratio: totalAbsValue > 0 ? item.value / totalAbsValue * 100 : 0,
  }))

  if (otherItems.length > 0) {
    const otherActual = otherItems.reduce((sum, item) => sum + item.actualValue, 0)
    const otherAbs = otherItems.reduce((sum, item) => sum + item.value, 0)
    result.push({
      key: `other-${mode}`,
      name: '其他持仓',
      code: 'OTHER',
      actualValue: otherActual,
      value: otherAbs,
      color: '#94a3b8',
      ratio: totalAbsValue > 0 ? otherAbs / totalAbsValue * 100 : 0,
    })
  }

  return result
}

function PnlAttributionChart({
  title,
  subtitle,
  emptyText,
  data,
}: {
  title: string
  subtitle: string
  emptyText: string
  data: Array<{
    key: string
    name: string
    code: string
    actualValue: number
    value: number
    color: string
    ratio: number
  }>
}) {
  const totalAbsolute = data.reduce((sum, item) => sum + item.value, 0)

  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader className="space-y-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex h-72 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
            {emptyText}
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[minmax(220px,280px)_1fr] lg:items-center">
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <RechartsPie>
                  <Pie
                    data={data}
                    cx="50%"
                    cy="50%"
                    innerRadius={64}
                    outerRadius={100}
                    paddingAngle={2}
                    strokeWidth={0}
                    dataKey="value"
                    nameKey="name"
                  >
                    {data.map((entry) => (
                      <Cell key={entry.key} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: number, _name, payload) => {
                      const item = payload?.payload
                      return [`${formatCurrency(item.actualValue)} | 绝对值 ${formatCurrency(value)}`, item?.name]
                    }}
                  />
                </RechartsPie>
              </ResponsiveContainer>
            </div>

            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/20 p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">图注说明</div>
                <p className="mt-2 text-sm text-muted-foreground">
                  饼图按各持仓盈亏贡献的绝对值切分，面积越大表示对整体盈亏影响越明显；右侧图注显示持仓名称、实际盈亏金额和占比。
                </p>
                <div className="mt-3 text-sm font-medium">绝对值合计 {formatCurrency(totalAbsolute)}</div>
              </div>

              <div className="space-y-3">
                {data.map((item) => (
                  <div key={item.key} className="space-y-2 rounded-xl border border-slate-200 p-3">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                        <span>{item.name}</span>
                        {item.code !== 'OTHER' && <span className="text-xs text-muted-foreground">({item.code})</span>}
                      </div>
                      <div className="text-right">
                        <div className={`text-sm font-medium ${item.actualValue >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                          {item.actualValue >= 0 ? '+' : ''}{formatCurrency(item.actualValue).replace('¥', '')}
                        </div>
                        <div className="text-xs text-muted-foreground">{item.ratio.toFixed(1)}%</div>
                      </div>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${item.ratio}%`, backgroundColor: item.color }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function PortfolioSummaryCard({
  summary,
  portfolios = [],
  accountBalance,
  onAccountBalanceChange,
  showPnlAttribution = false,
  showDistribution = true,
  showExposureAnalysis = true,
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
  const totalPnlAttribution = buildPnlAttributionData(portfolios, 'total')
  const todayPnlAttribution = buildPnlAttributionData(portfolios, 'today')

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总市值</CardTitle>
          <Wallet className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="break-all text-xl font-bold sm:text-2xl">¥{summary.total_market_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">可用资金</CardTitle>
          <Wallet className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="break-all text-xl font-bold sm:text-2xl">
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
          <CardTitle className="text-sm font-medium">总金额</CardTitle>
          <PieChart className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="break-all text-xl font-bold sm:text-2xl">
            ¥{((summary?.total_market_value ?? 0) + (accountBalance ?? 0)).toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            持仓 {summary?.total_market_value?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '0.00'} + 可用 {(accountBalance ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">总盈亏</CardTitle>
          {summary.total_pnl >= 0 ? <TrendingUp className="h-4 w-4 text-red-500" /> : <TrendingDown className="h-4 w-4 text-green-500" />}
        </CardHeader>
        <CardContent>
          <div className={`break-words text-xl font-bold sm:text-2xl ${summary.total_pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>
            {summary.total_pnl >= 0 ? '+' : ''}{summary.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })} ({summary.total_pnl_pct.toFixed(2)}%)
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">今日盈亏</CardTitle>
          {summary.today_pnl === null ? (
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          ) : summary.today_pnl >= 0 ? (
            <TrendingUp className="h-4 w-4 text-red-500" />
          ) : (
            <TrendingDown className="h-4 w-4 text-green-500" />
          )}
        </CardHeader>
        <CardContent>
          <div className={`break-words text-xl font-bold sm:text-2xl ${summary.today_pnl === null ? 'text-muted-foreground' : summary.today_pnl >= 0 ? 'text-red-500' : 'text-green-500'}`}>
            {summary.today_pnl !== null
              ? `${summary.today_pnl >= 0 ? '+' : ''}${summary.today_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}${summary.today_pnl_pct !== null ? ` (${summary.today_pnl_pct.toFixed(2)}%)` : ''}`
              : '-'}
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

      {showDistribution && distributionData.length > 0 && (
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

      {showExposureAnalysis && summary.exposure_analysis && (
        <Card className="md:col-span-2 lg:col-span-5">
          <CardHeader>
            <CardTitle className="text-sm font-medium">持仓暴露分析</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-3">
              <ExposureList title="资产桶" items={summary.exposure_analysis.asset_bucket} />
              <ExposureList title="地域" items={summary.exposure_analysis.region} />
              <ExposureList title="风格" items={summary.exposure_analysis.style} />
            </div>
            {summary.exposure_analysis.risk_tags.length > 0 && (
              <div className="rounded-lg border bg-muted/20 p-4">
                <div className="text-sm font-semibold">风险标签</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {summary.exposure_analysis.risk_tags.map((item) => (
                    <span key={item.name} className="rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground">
                      {item.name} {item.ratio.toFixed(1)}%
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="space-y-2">
              {summary.exposure_analysis.alerts.map((alert) => (
                <div key={alert.message} className={`rounded-lg border px-3 py-2 text-sm ${alert.level === 'high' ? 'border-red-200 bg-red-50 text-red-700' : alert.level === 'medium' ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                  {alert.message}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}


      {showExposureAnalysis && summary.rebalance_plan && (
        <Card className="md:col-span-2 lg:col-span-5">
          <CardHeader>
            <CardTitle className="text-sm font-medium">再平衡建议</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border bg-muted/20 p-4">
                <div className="text-xs text-muted-foreground">总资产口径</div>
                <div className="mt-1 text-lg font-semibold">{formatCurrency(summary.rebalance_plan.total_assets)}</div>
              </div>
              <div className="rounded-lg border bg-muted/20 p-4">
                <div className="text-xs text-muted-foreground">单项调仓上限</div>
                <div className="mt-1 text-lg font-semibold">{formatCurrency(summary.rebalance_plan.single_adjustment_limit)}</div>
              </div>
              <div className="rounded-lg border bg-muted/20 p-4 sm:col-span-2">
                <div className="text-xs text-muted-foreground">执行原则</div>
                <div className="mt-1 text-sm text-muted-foreground">目标仓位会随宏观时钟动态调整，执行状态同时考虑红绿灯、跨境风控和四因子。</div>
              </div>
            </div>

            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-muted-foreground">
                  <tr>
                    <th className="py-2 pl-4 pr-3">资产桶</th>
                    <th className="py-2 pr-3">当前</th>
                    <th className="py-2 pr-3">目标</th>
                    <th className="py-2 pr-3">偏离</th>
                    <th className="py-2 pr-3">建议金额</th>
                    <th className="py-2 pr-4">执行状态</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.rebalance_plan.items.map((item) => (
                    <tr key={item.name} className="border-b last:border-0">
                      <td className="py-3 pl-4 pr-3 font-medium">{item.name}</td>
                      <td className="py-3 pr-3">
                        <div className="font-mono">{item.current_ratio.toFixed(1)}%</div>
                        <div className="text-xs text-muted-foreground">{formatCurrency(item.current_value)}</div>
                      </td>
                      <td className="py-3 pr-3 font-mono">{item.target_ratio.toFixed(1)}%</td>
                      <td className={`py-3 pr-3 font-mono ${item.deviation_ratio > 0 ? 'text-amber-700' : item.deviation_ratio < 0 ? 'text-blue-700' : ''}`}>
                        {item.deviation_ratio > 0 ? '+' : ''}{item.deviation_ratio.toFixed(1)}%
                      </td>
                      <td className={`py-3 pr-3 font-mono ${item.suggested_amount > 0 ? 'text-red-600' : item.suggested_amount < 0 ? 'text-green-600' : 'text-muted-foreground'}`}>
                        {item.suggested_amount > 0 ? '+' : ''}{formatCurrency(item.suggested_amount)}
                      </td>
                      <td className="py-3 pr-4">
                        <Badge variant="outline" className={rebalanceStatusClass(item.execution_status)}>{item.execution_label}</Badge>
                        <div className="mt-2 text-xs text-muted-foreground">{item.action}</div>
                        <div className="mt-1 max-w-[360px] text-xs leading-5 text-muted-foreground">{item.reason}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="space-y-2">
              {summary.rebalance_plan.notes.map((note) => (
                <div key={note} className="rounded-lg border bg-muted/20 px-3 py-2 text-sm text-muted-foreground">{note}</div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {showPnlAttribution && (
        <div className="md:col-span-2 lg:col-span-5 grid gap-4 xl:grid-cols-2">
          <PnlAttributionChart
            title="总盈亏归因"
            subtitle="下方饼图展示当前总盈亏主要由哪些持仓贡献。"
            emptyText="暂无可展示的总盈亏归因数据"
            data={totalPnlAttribution}
          />
          <PnlAttributionChart
            title="今日盈亏归因"
            subtitle="下方饼图展示今日涨跌主要来自哪些持仓。"
            emptyText="暂无可展示的今日盈亏归因数据"
            data={todayPnlAttribution}
          />
        </div>
      )}
    </div>
  )
}

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type AdviceResponse } from '@/services/api'
import { TrendingUp, TrendingDown, Minus, Plus, ArrowDownRight, Lightbulb } from 'lucide-react'

interface AdviceCardProps {
  advice: AdviceResponse
  accountBalance?: number
}

const adviceTypeConfig: Record<string, { label: string; color: string; icon: typeof TrendingUp }> = {
  buy: { label: '买入', color: 'bg-red-500', icon: TrendingUp },
  sell: { label: '卖出', color: 'bg-green-500', icon: TrendingDown },
  hold: { label: '持有', color: 'bg-gray-500', icon: Minus },
  add: { label: '加仓', color: 'bg-orange-500', icon: Plus },
  reduce: { label: '减仓', color: 'bg-yellow-500', icon: ArrowDownRight },
}

export function AdviceCard({ advice, accountBalance = 0 }: AdviceCardProps) {
  const config = adviceTypeConfig[advice.advice_type] || adviceTypeConfig.hold
  const Icon = config.icon

  const calculateSuggestedPosition = () => {
    if (!accountBalance || !advice.current_price) return null

    let positionRatio = 0
    switch (advice.advice_type) {
      case 'buy':
        positionRatio = 0.3 * (advice.confidence / 100)
        break
      case 'add':
        positionRatio = 0.2 * (advice.confidence / 100)
        break
      case 'reduce':
        positionRatio = 0.15 * (advice.confidence / 100)
        break
      case 'sell':
        positionRatio = 1.0
        break
      default:
        return null
    }

    const suggestedAmount = accountBalance * positionRatio
    const suggestedShares = Math.floor(suggestedAmount / advice.current_price)

    return {
      amount: suggestedAmount,
      shares: suggestedShares,
      ratio: positionRatio * 100,
    }
  }

  const suggestedPosition = calculateSuggestedPosition()

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-lg">{advice.etf_name || advice.etf_code}</CardTitle>
          <span className="font-mono text-sm text-muted-foreground">{advice.etf_code}</span>
        </div>
        <span className={`${config.color} flex items-center gap-1 rounded-full px-3 py-1 text-sm font-medium text-white`}>
          <Icon className="h-3 w-3" />
          {config.label}
        </span>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">当前价格</span>
            <span className="font-medium">{advice.current_price?.toFixed(3) || '-'}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">浮动盈亏</span>
            <span className={`font-medium ${advice.pnl_pct && advice.pnl_pct > 0 ? 'text-red-500' : advice.pnl_pct && advice.pnl_pct < 0 ? 'text-green-500' : ''}`}>
              {advice.pnl_pct ? `${advice.pnl_pct.toFixed(2)}%` : '-'}
            </span>
          </div>
          {suggestedPosition && (advice.advice_type === 'buy' || advice.advice_type === 'add') && (
            <div className="flex items-center justify-between rounded bg-muted/50 p-2 text-sm">
              <span className="text-muted-foreground">建议仓位</span>
              <div className="text-right">
                <span className="font-medium">{suggestedPosition.shares} 股</span>
                <span className="ml-1 text-xs text-muted-foreground">({suggestedPosition.ratio.toFixed(1)}%资金)</span>
              </div>
            </div>
          )}
          <div className="border-t pt-2">
            <div className="flex items-start gap-2">
              <Lightbulb className="mt-0.5 h-4 w-4 flex-shrink-0 text-yellow-500" />
              <div className="w-full space-y-3">
                <div className="rounded-xl border bg-primary/5 p-4">
                  <div className="text-xs font-medium text-muted-foreground">主建议</div>
                  <p className="mt-2 text-sm leading-relaxed">
                    {advice.main_judgment || `中期以${config.label}为主，${advice.medium_term.conclusion}`}
                  </p>
                  {advice.summary && (
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                      {advice.summary}
                    </p>
                  )}
                  {(advice.why.length > 0 || advice.news_basis.length > 0 || advice.policy_basis.length > 0) && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {advice.why.slice(0, 3).map((item, index) => (
                        <span key={`why-${index}`} className="rounded-full border bg-background px-2.5 py-1 text-xs text-foreground/80">
                          {item}
                        </span>
                      ))}
                      {advice.news_basis[0] && (
                        <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800">
                          新闻：{advice.news_basis[0]}
                        </span>
                      )}
                      {advice.policy_basis[0] && (
                        <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs text-violet-800">
                          政策：{advice.policy_basis[0]}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div className="rounded-xl border bg-background/60 p-4">
                  <div className="text-xs font-medium text-muted-foreground">补充判断</div>
                  <div className="mt-2 space-y-3 text-sm">
                    <div>
                      <span className="font-medium">短期：</span>
                      <span>{advice.short_term.action}，{advice.short_term.conclusion}</span>
                      {(advice.short_term.signals[0] || advice.short_term.risks[0]) && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {advice.short_term.signals[0] ? `依据：${advice.short_term.signals[0]}` : ''}
                          {advice.short_term.signals[0] && advice.short_term.risks[0] ? '；' : ''}
                          {advice.short_term.risks[0] ? `风险：${advice.short_term.risks[0]}` : ''}
                        </p>
                      )}
                    </div>
                    <div>
                      <span className="font-medium">长期：</span>
                      <span>{advice.long_term.action}，{advice.long_term.conclusion}</span>
                      {(advice.long_term.signals[0] || advice.long_term.risks[0]) && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {advice.long_term.signals[0] ? `依据：${advice.long_term.signals[0]}` : ''}
                          {advice.long_term.signals[0] && advice.long_term.risks[0] ? '；' : ''}
                          {advice.long_term.risks[0] ? `风险：${advice.long_term.risks[0]}` : ''}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between pt-2 text-sm">
            <span className="text-muted-foreground">置信度</span>
            <div className="flex items-center gap-2">
              <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${advice.confidence}%` }} />
              </div>
              <span className="w-10 text-right font-medium">{advice.confidence}%</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

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

  // 计算建议仓位
  const calculateSuggestedPosition = () => {
    if (!accountBalance || !advice.current_price) return null
    
    // 根据建议类型和置信度计算仓位比例
    let positionRatio = 0
    switch (advice.advice_type) {
      case 'buy':
        positionRatio = 0.3 * (advice.confidence / 100) // 买入: 30% 资金 * 置信度
        break
      case 'add':
        positionRatio = 0.2 * (advice.confidence / 100) // 加仓: 20% 资金 * 置信度
        break
      case 'reduce':
        positionRatio = 0.15 * (advice.confidence / 100) // 减仓: 15% 估算
        break
      case 'sell':
        positionRatio = 1.0 // 卖出: 全部
        break
      default:
        return null
    }
    
    const suggestedAmount = accountBalance * positionRatio
    const suggestedShares = Math.floor(suggestedAmount / advice.current_price)
    
    return {
      amount: suggestedAmount,
      shares: suggestedShares,
      ratio: positionRatio * 100
    }
  }

  const suggestedPosition = calculateSuggestedPosition()

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <div className="flex items-center gap-2">
          <CardTitle className="text-lg">{advice.etf_name || advice.etf_code}</CardTitle>
          <span className="text-sm text-muted-foreground font-mono">{advice.etf_code}</span>
        </div>
        <span className={`${config.color} text-white px-3 py-1 rounded-full text-sm font-medium flex items-center gap-1`}>
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
            <div className="flex items-center justify-between text-sm bg-muted/50 p-2 rounded">
              <span className="text-muted-foreground">建议仓位</span>
              <div className="text-right">
                <span className="font-medium">{suggestedPosition.shares} 股</span>
                <span className="text-xs text-muted-foreground ml-1">({suggestedPosition.ratio.toFixed(1)}%资金)</span>
              </div>
            </div>
          )}
          <div className="pt-2 border-t">
            <div className="flex items-start gap-2">
              <Lightbulb className="h-4 w-4 text-yellow-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm">{advice.reason}</p>
            </div>
          </div>
          <div className="flex items-center justify-between text-sm pt-2">
            <span className="text-muted-foreground">置信度</span>
            <div className="flex items-center gap-2">
              <div className="w-24 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${advice.confidence}%` }}
                />
              </div>
              <span className="font-medium w-10 text-right">{advice.confidence}%</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

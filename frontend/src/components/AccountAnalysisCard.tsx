import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { AccountAnalysisResponse } from '@/services/api'
import { AlertTriangle, Clock, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react'

interface AccountAnalysisCardProps {
  analysis: AccountAnalysisResponse
}

const riskConfig = {
  low: {
    label: '低风险',
    className: 'text-green-700 border-green-200 bg-green-50',
    icon: ShieldCheck,
  },
  medium: {
    label: '中风险',
    className: 'text-yellow-700 border-yellow-200 bg-yellow-50',
    icon: AlertTriangle,
  },
  high: {
    label: '高风险',
    className: 'text-red-700 border-red-200 bg-red-50',
    icon: ShieldAlert,
  },
} as const

export function AccountAnalysisCard({ analysis }: AccountAnalysisCardProps) {
  const config = riskConfig[analysis.risk_level as keyof typeof riskConfig] ?? riskConfig.medium
  const RiskIcon = config.icon

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <CardTitle>账户投资建议</CardTitle>
            </div>
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              决策时间 {new Date(analysis.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
            </div>
          </div>
          <Badge variant="outline" className={config.className}>
            <RiskIcon className="h-3.5 w-3.5 mr-1" />
            {config.label}
          </Badge>
        </div>
        <p className="text-sm leading-relaxed text-muted-foreground">{analysis.summary}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border bg-muted/30 p-4">
            <div className="text-sm font-medium">仓位建议</div>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{analysis.position_advice}</p>
          </div>
          <div className="rounded-lg border bg-muted/30 p-4">
            <div className="text-sm font-medium">调仓建议</div>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{analysis.rebalance_advice}</p>
          </div>
        </div>

        <div className="rounded-lg border p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium">关键操作</div>
            <span className="text-xs text-muted-foreground">置信度 {analysis.confidence.toFixed(0)}%</span>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {analysis.key_actions.map((action, index) => (
              <div key={`${index}-${action}`} className="text-sm text-muted-foreground">
                {index + 1}. {action}
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

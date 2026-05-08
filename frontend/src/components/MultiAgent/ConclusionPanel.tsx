import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { type MultiAgentArbiterSummary, type MultiAgentFinalConclusion } from '@/services/api'

const actionStyleMap: Record<string, string> = {
  buy: 'border-red-200 bg-red-50 text-red-700',
  add: 'border-orange-200 bg-orange-50 text-orange-700',
  hold: 'border-blue-200 bg-blue-50 text-blue-700',
  reduce: 'border-amber-200 bg-amber-50 text-amber-700',
  sell: 'border-emerald-200 bg-emerald-50 text-emerald-700',
}

const actionLabelMap: Record<string, string> = {
  buy: '买入',
  add: '加仓',
  hold: '持有',
  reduce: '减仓',
  sell: '卖出',
}

function ConfidenceBar({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value))
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${safeValue}%` }} />
      </div>
      <span className="min-w-12 text-right text-xs font-mono text-muted-foreground">{safeValue.toFixed(0)}%</span>
    </div>
  )
}

export function ConclusionPanel({
  conclusion,
  arbiter,
}: {
  conclusion: MultiAgentFinalConclusion | null
  arbiter?: MultiAgentArbiterSummary | null
}) {
  if (!conclusion) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">最终结论</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          运行一次研判后，这里会展示共识动作、支持角色、分歧和风险提示。
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-base">最终结论</CardTitle>
          <Badge variant="outline" className={actionStyleMap[conclusion.recommended_action] || actionStyleMap.hold}>
            {actionLabelMap[conclusion.recommended_action] || conclusion.recommended_action}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">{conclusion.action || '暂无动作说明'}</p>
      </CardHeader>
      <CardContent className="space-y-5">
        <ConfidenceBar value={conclusion.confidence} />
        <div className="rounded-lg border bg-primary/5 p-4 text-sm leading-relaxed">
          {conclusion.conclusion}
        </div>

        {arbiter && (
          <div className="space-y-3 rounded-lg border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">裁决摘要</div>
              <Badge variant="outline">
                {arbiter.consensus_reached ? '已收敛' : arbiter.convergence_state}
              </Badge>
            </div>
            <div className="text-sm text-muted-foreground">{arbiter.why_stop}</div>
            {arbiter.strong_opposition.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">强烈反对</div>
                <div className="space-y-2">
                  {arbiter.strong_opposition.map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm leading-relaxed text-foreground/80">
                      {item}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {conclusion.supporting_roles.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">支持角色</div>
            <div className="flex flex-wrap gap-2">
              {conclusion.supporting_roles.map((item) => (
                <Badge key={item} variant="outline" className="bg-background">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {conclusion.disagreements.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">主要分歧</div>
            <div className="space-y-2">
              {conclusion.disagreements.map((item, index) => (
                <div key={`${item}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm leading-relaxed text-foreground/80">
                  {item}
                </div>
              ))}
            </div>
          </div>
        )}

        {conclusion.risk_notes.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">风险提示</div>
            <div className="space-y-2">
              {conclusion.risk_notes.map((item, index) => (
                <div key={`${item}-${index}`} className="rounded-lg border border-dashed bg-muted/20 px-3 py-2 text-sm leading-relaxed text-muted-foreground">
                  {item}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { type MultiAgentRoleOpinion } from '@/services/api'

const stanceStyleMap: Record<MultiAgentRoleOpinion['stance'], string> = {
  bullish: 'border-red-200 bg-red-50 text-red-700',
  neutral: 'border-slate-200 bg-slate-50 text-slate-700',
  bearish: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  mixed: 'border-amber-200 bg-amber-50 text-amber-700',
}

const stanceLabelMap: Record<MultiAgentRoleOpinion['stance'], string> = {
  bullish: '偏多',
  neutral: '中性',
  bearish: '偏空',
  mixed: '分歧',
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

export function RoleOpinionCard({ opinion }: { opinion: MultiAgentRoleOpinion }) {
  return (
    <Card className="h-full">
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">{opinion.role_name}</CardTitle>
              <Badge variant="outline" className="bg-background text-xs">
                第 {opinion.round_index} 轮
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">{opinion.summary}</p>
          </div>
          <Badge variant="outline" className={stanceStyleMap[opinion.stance]}>
            {stanceLabelMap[opinion.stance]}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          建议动作：{opinion.action || '暂无'}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ConfidenceBar value={opinion.confidence} />
        {opinion.evidence.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">证据</div>
            <div className="space-y-2">
              {opinion.evidence.map((item, index) => (
                <div key={`${item}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm leading-relaxed text-foreground/80">
                  {item}
                </div>
              ))}
            </div>
          </div>
        )}
        {opinion.risk_notes.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">风险提示</div>
            <div className="space-y-2">
              {opinion.risk_notes.map((item, index) => (
                <div key={`${item}-${index}`} className="rounded-lg border border-dashed bg-muted/20 px-3 py-2 text-sm leading-relaxed text-muted-foreground">
                  {item}
                </div>
              ))}
            </div>
          </div>
        )}
        {opinion.rebuttals && opinion.rebuttals.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">反驳 / 回应</div>
            <div className="space-y-2">
              {opinion.rebuttals.map((item, index) => (
                <div key={`${item}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm leading-relaxed text-foreground/80">
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

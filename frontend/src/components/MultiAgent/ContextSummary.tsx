import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { type MultiAgentContextSummary, type MultiAgentRunResponse } from '@/services/api'

const sceneLabelMap: Record<MultiAgentContextSummary['scenario'], string> = {
  etf: 'ETF',
  account: '账户',
  general: '通用',
}

export function ContextSummary({
  summary,
  run,
}: {
  summary: MultiAgentContextSummary | null
  run?: MultiAgentRunResponse | null
}) {
  if (!summary) {
    return (
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">上下文摘要</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          先运行一次研判，系统会自动汇总当前持仓、账户和问题上下文。
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{sceneLabelMap[summary.scenario]}</Badge>
          {run?.llm_provider && <Badge variant="outline">LLM: {run.llm_provider}</Badge>}
          {typeof run?.max_debate_rounds === 'number' && (
            <Badge variant="outline">最大轮数 {run.max_debate_rounds}</Badge>
          )}
          {run && (
            <Badge variant="outline">{run.collapse_debate_by_default ? '默认折叠' : '默认展开'}</Badge>
          )}
          <CardTitle className="text-base">{summary.title}</CardTitle>
        </div>
        {summary.question && (
          <p className="text-sm text-muted-foreground">问题：{summary.question}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {summary.metrics && Object.keys(summary.metrics).length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Object.entries(summary.metrics).map(([key, value]) => (
              <div key={key} className="rounded-lg border bg-muted/20 px-3 py-2">
                <div className="text-xs text-muted-foreground">{key}</div>
                <div className="mt-1 text-sm font-medium">{value}</div>
              </div>
            ))}
          </div>
        )}
        <div className="space-y-2">
          {summary.bullets.map((bullet, index) => (
            <div key={`${bullet}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm leading-relaxed text-foreground/80">
              {bullet}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

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
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Badge variant="outline">{sceneLabelMap[summary.scenario]}</Badge>
            <CardTitle className="truncate text-base">{summary.title}</CardTitle>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {run?.llm_provider && <Badge variant="outline">LLM: {run.llm_provider}</Badge>}
            {typeof run?.max_debate_rounds === 'number' && (
              <Badge variant="outline">{run.max_debate_rounds} 轮</Badge>
            )}
          </div>
        </div>
        {summary.question && (
          <p className="truncate text-sm text-muted-foreground">问题：{summary.question}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        {summary.metrics && Object.keys(summary.metrics).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(summary.metrics).slice(0, 3).map(([key, value]) => (
              <Badge key={key} variant="secondary" className="max-w-full truncate font-normal">
                {key}: {value}
              </Badge>
            ))}
          </div>
        )}
        <div className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
          {summary.bullets.slice(0, 2).map((bullet, index) => (
            <div key={`${bullet}-${index}`} className="truncate">
              {bullet}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

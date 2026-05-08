import { useEffect, useMemo, useState } from 'react'
import { Bot, Clock, ChevronDown, ChevronUp, RefreshCw, Sparkles } from 'lucide-react'

import {
  multiAgentApi,
  type MultiAgentContextSummary,
  type MultiAgentDebateRound,
  type MultiAgentRunResponse,
  type MultiAgentScene,
} from '@/services/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { formatBeijingTime } from '@/utils/time'
import { ContextSummary } from '@/components/MultiAgent/ContextSummary'
import { RoleOpinionCard } from '@/components/MultiAgent/RoleOpinionCard'
import { ConclusionPanel } from '@/components/MultiAgent/ConclusionPanel'

const sceneLabelMap: Record<MultiAgentScene, string> = {
  etf: 'ETF',
  account: '账户',
  general: '通用',
}

const sceneDescriptionMap: Record<MultiAgentScene, string> = {
  etf: '围绕单只 ETF 的买卖、加减仓和节奏判断。',
  account: '围绕组合结构、现金比例与再平衡。',
  general: '围绕一般投资问题与最新信息研判。',
}

const convergenceLabelMap: Record<MultiAgentDebateRound['convergence_state'], string> = {
  forming: '形成中',
  contested: '分歧中',
  converged: '已收敛',
  max_rounds: '已达上限',
  failed: '失败',
}

function RunHistoryItem({
  run,
  active,
  onClick,
}: {
  run: MultiAgentRunResponse
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-xl border p-3 text-left transition-colors ${
        active ? 'border-primary bg-primary/5' : 'hover:border-primary/40 hover:bg-muted/30'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{run.context_summary.title}</div>
          <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {run.context_summary.bullets[0] || '暂无摘要'}
          </div>
        </div>
        <Badge variant="outline">{sceneLabelMap[run.scene]}</Badge>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>{run.final_conclusion.recommended_action}</span>
          {run.llm_provider && <Badge variant="outline" className="bg-background">{run.llm_provider}</Badge>}
        </div>
        <span>{formatBeijingTime(run.created_at, { hour: '2-digit', minute: '2-digit' }, '')}</span>
      </div>
    </button>
  )
}

export function MultiAgentWorkbenchPage() {
  const [scene, setScene] = useState<MultiAgentScene>('etf')
  const [question, setQuestion] = useState('')
  const [usePortfolioContext, setUsePortfolioContext] = useState(true)
  const [maxDebateRounds, setMaxDebateRounds] = useState(3)
  const [collapseDebateByDefault, setCollapseDebateByDefault] = useState(true)
  const [runs, setRuns] = useState<MultiAgentRunResponse[]>([])
  const [currentRun, setCurrentRun] = useState<MultiAgentRunResponse | null>(null)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [showTranscript, setShowTranscript] = useState(false)

  const currentContext = useMemo<MultiAgentContextSummary | null>(() => currentRun?.context_summary ?? null, [currentRun])
  const currentInitialOpinions = currentRun?.initial_role_opinions ?? []
  const currentDebateRounds = currentRun?.debate_rounds ?? []
  const currentArbiter = currentRun?.arbiter_summary ?? null

  useEffect(() => {
    setShowTranscript(currentRun ? !currentRun.collapse_debate_by_default : false)
  }, [currentRun?.run_id])

  const loadRuns = async () => {
    setLoadingHistory(true)
    setMessage(null)
    try {
      const res = await multiAgentApi.listRuns()
      setRuns(res.data.runs)
      if (!currentRun && res.data.runs.length > 0) {
        setCurrentRun(res.data.runs[0])
      }
    } catch (error: any) {
      console.error('Failed to load multi-agent runs:', error)
      setMessage(error.response?.data?.detail || '加载历史失败')
    } finally {
      setLoadingHistory(false)
    }
  }

  const handleRun = async () => {
    setRunning(true)
    setMessage(null)
    try {
      const res = await multiAgentApi.createRun({
        scene,
        question: question.trim() || undefined,
        use_portfolio_context: usePortfolioContext,
        max_debate_rounds: maxDebateRounds,
        collapse_debate_by_default: collapseDebateByDefault,
      })
      setCurrentRun(res.data)
      setShowTranscript(!res.data.collapse_debate_by_default)
      setRuns((prev) => [res.data, ...prev.filter((item) => item.run_id !== res.data.run_id)])
    } catch (error: any) {
      console.error('Failed to create multi-agent run:', error)
      setMessage(error.response?.data?.detail || '研判失败')
    } finally {
      setRunning(false)
    }
  }

  const handleLoadRun = async (runId: number) => {
    const localRun = runs.find((item) => item.run_id === runId)
    if (localRun) {
      setCurrentRun(localRun)
      setShowTranscript(!localRun.collapse_debate_by_default)
      return
    }
    setMessage(null)
    try {
      const res = await multiAgentApi.getRun(runId)
      setCurrentRun(res.data)
      setShowTranscript(!res.data.collapse_debate_by_default)
    } catch (error: any) {
      console.error('Failed to load run detail:', error)
      setMessage(error.response?.data?.detail || '加载研判详情失败')
    }
  }

  useEffect(() => {
    loadRuns()
  }, [])

  const activeRunId = currentRun?.run_id ?? runs[0]?.run_id ?? null

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            <h1 className="text-2xl font-bold sm:text-3xl">多智能体投资研判工作台</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            独立于现有助手的多角色研判入口，默认接入当前持仓、账户和最新搜索能力。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={loadRuns} disabled={loadingHistory}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loadingHistory ? 'animate-spin' : ''}`} />
            刷新历史
          </Button>
          <Button onClick={handleRun} disabled={running}>
            <Sparkles className="mr-2 h-4 w-4" />
            {running ? '研判中...' : '开始研判'}
          </Button>
        </div>
      </div>

      {message && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {message}
        </div>
      )}

      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">研判设置</CardTitle>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch checked={usePortfolioContext} onCheckedChange={setUsePortfolioContext} />
              <span>引用持仓信息</span>
            </div>
          </div>
          <Tabs value={scene} onValueChange={(value) => setScene(value as MultiAgentScene)}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="etf">ETF</TabsTrigger>
              <TabsTrigger value="account">账户</TabsTrigger>
              <TabsTrigger value="general">通用</TabsTrigger>
            </TabsList>
            <TabsContent value={scene} className="mt-4">
              <div className="rounded-lg border bg-muted/20 p-4">
                <div className="text-sm font-medium">{sceneLabelMap[scene]} 场景</div>
                <p className="mt-1 text-sm text-muted-foreground">{sceneDescriptionMap[scene]}</p>
              </div>
            </TabsContent>
          </Tabs>
          <div className="space-y-2">
            <label className="text-sm font-medium">问题</label>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="输入 ETF / 账户 / 通用问题。留空时将主要围绕当前持仓和市场上下文进行研判。"
              className="min-h-28 w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus:ring-1 focus:ring-primary"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              默认启用持仓上下文和搜索
            </span>
          </div>
          <div className="grid gap-3 pt-2 sm:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium">最大辩论轮数</span>
              <input
                type="number"
                min={1}
                max={8}
                value={maxDebateRounds}
                onChange={(event) => setMaxDebateRounds(Math.max(1, Math.min(8, Number(event.target.value) || 1)))}
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-primary focus:ring-1 focus:ring-primary"
              />
            </label>
            <div className="flex items-end justify-between rounded-lg border bg-muted/20 px-3 py-2">
              <div className="space-y-1">
                <div className="text-sm font-medium">默认折叠辩论过程</div>
                <div className="text-xs text-muted-foreground">运行后先显示裁决结论，辩论过程默认收起。</div>
              </div>
              <Switch checked={collapseDebateByDefault} onCheckedChange={setCollapseDebateByDefault} />
            </div>
          </div>
        </CardHeader>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">历史记录</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {loadingHistory ? (
              <div className="py-10 text-center text-sm text-muted-foreground">加载历史中...</div>
            ) : runs.length > 0 ? (
              runs.map((run) => (
                <RunHistoryItem
                  key={run.run_id}
                  run={run}
                  active={run.run_id === activeRunId}
                  onClick={() => void handleLoadRun(run.run_id)}
                />
              ))
            ) : (
              <div className="py-10 text-center text-sm text-muted-foreground">暂无历史记录</div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <ContextSummary summary={currentContext} run={currentRun} />

          <ConclusionPanel conclusion={currentRun?.final_conclusion ?? null} arbiter={currentArbiter} />

          <Card>
            <CardHeader className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle className="text-base">完整辩论过程</CardTitle>
                <div className="flex items-center gap-2">
                  {currentRun && (
                    <Badge variant="outline">
                      {currentDebateRounds.length + 1} 轮 / {currentRun.max_debate_rounds} 上限
                    </Badge>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowTranscript((value) => !value)}
                    disabled={!currentRun}
                  >
                    {showTranscript ? (
                      <>
                        <ChevronUp className="mr-2 h-4 w-4" />
                        收起
                      </>
                    ) : (
                      <>
                        <ChevronDown className="mr-2 h-4 w-4" />
                        展开
                      </>
                    )}
                  </Button>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                {currentRun
                  ? `默认${currentRun.collapse_debate_by_default ? '折叠' : '展开'}；当前展示 ${currentRun.status}，LLM：${currentRun.llm_provider || 'unknown'}。`
                  : '先运行一次研判后，这里会展示初始分析、辩论轮次和裁决变化。'}
              </p>
            </CardHeader>
            {showTranscript && currentRun ? (
              <CardContent className="space-y-6">
                <section className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-sm font-medium">初始并行分析</div>
                      <div className="text-xs text-muted-foreground">所有角色的首轮分析会并行生成。</div>
                    </div>
                    <Badge variant="outline">{currentInitialOpinions.length} 个角色</Badge>
                  </div>
                  <div className="grid gap-4 lg:grid-cols-2">
                    {currentInitialOpinions.map((opinion) => (
                      <RoleOpinionCard key={`initial-${opinion.role_id}`} opinion={opinion} />
                    ))}
                  </div>
                </section>

                {currentDebateRounds.map((round) => (
                  <section key={round.round_index} className="space-y-3 rounded-2xl border bg-muted/10 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-medium">第 {round.round_index} 轮辩论</div>
                        <div className="text-xs text-muted-foreground">{round.round_summary}</div>
                      </div>
                      <Badge variant="outline">{convergenceLabelMap[round.convergence_state]}</Badge>
                    </div>

                    {round.arbiter_summary && (
                      <div className="rounded-lg border bg-background p-3 text-sm">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium">本轮裁决</span>
                          <Badge variant="outline">
                            {round.arbiter_summary.consensus_reached ? '已收敛' : '继续辩论'}
                          </Badge>
                        </div>
                        <div className="mt-2 text-muted-foreground">{round.arbiter_summary.why_stop}</div>
                      </div>
                    )}

                    {round.open_disagreements.length > 0 && (
                      <div className="space-y-2">
                        <div className="text-xs font-medium text-muted-foreground">未消解分歧</div>
                        <div className="space-y-2">
                          {round.open_disagreements.map((item, index) => (
                            <div key={`${round.round_index}-${item}-${index}`} className="rounded-lg border bg-background px-3 py-2 text-sm text-foreground/80">
                              {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="grid gap-4 lg:grid-cols-2">
                      {round.role_opinions.map((opinion) => (
                        <RoleOpinionCard key={`${round.round_index}-${opinion.role_id}`} opinion={opinion} />
                      ))}
                    </div>
                  </section>
                ))}
              </CardContent>
            ) : (
              <CardContent className="text-sm text-muted-foreground">
                {currentRun ? '辩论过程已折叠，点击“展开”查看每轮角色观点、反驳和裁决变化。' : '暂无辩论记录。'}
              </CardContent>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

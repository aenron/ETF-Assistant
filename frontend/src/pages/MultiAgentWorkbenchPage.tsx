import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, CheckCircle2, Clock, ChevronDown, ChevronUp, Pencil, RefreshCw, Sparkles, Trash2 } from 'lucide-react'

import {
  multiAgentApi,
  portfolioApi,
  type PortfolioWithMarket,
  type MultiAgentContextSummary,
  type MultiAgentArbiterSummary,
  type MultiAgentDebateRound,
  type MultiAgentFinalConclusion,
  type MultiAgentRoleOpinion,
  type MultiAgentRunResponse,
  type MultiAgentScene,
} from '@/services/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ContextSummary } from '@/components/MultiAgent/ContextSummary'
import { RoleOpinionCard } from '@/components/MultiAgent/RoleOpinionCard'
import { ConclusionPanel } from '@/components/MultiAgent/ConclusionPanel'
import { ConfirmDialog } from '@/components/ConfirmDialog'

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

type DebateChatMessage = {
  id: string
  kind: 'status' | 'round' | 'role' | 'arbiter' | 'final' | 'error' | 'user'
  roleId?: string
  roundIndex?: number
  speaker: string
  content: string
  detail?: string
  stance?: MultiAgentRoleOpinion['stance']
  confidence?: number
  streaming?: boolean
}

const stanceLabelMap: Record<MultiAgentRoleOpinion['stance'], string> = {
  bullish: '偏多',
  neutral: '中性',
  bearish: '偏空',
  mixed: '分歧',
}

const stanceBubbleMap: Record<MultiAgentRoleOpinion['stance'], string> = {
  bullish: 'border-red-200 bg-red-50',
  neutral: 'border-slate-200 bg-white',
  bearish: 'border-emerald-200 bg-emerald-50',
  mixed: 'border-amber-200 bg-amber-50',
}

const roleAvatarMap: Record<string, { label: string; className: string }> = {
  policy_event: { label: '策', className: 'bg-red-100 text-red-700 ring-red-200' },
  technical: { label: '技', className: 'bg-sky-100 text-sky-700 ring-sky-200' },
  allocation: { label: '配', className: 'bg-violet-100 text-violet-700 ring-violet-200' },
  risk_arbiter: { label: '风', className: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
  portfolio_structure: { label: '组', className: 'bg-blue-100 text-blue-700 ring-blue-200' },
  rebalance: { label: '衡', className: 'bg-orange-100 text-orange-700 ring-orange-200' },
  risk_exposure: { label: '险', className: 'bg-rose-100 text-rose-700 ring-rose-200' },
  capital_executor: { label: '资', className: 'bg-cyan-100 text-cyan-700 ring-cyan-200' },
  researcher: { label: '研', className: 'bg-indigo-100 text-indigo-700 ring-indigo-200' },
  counterpoint: { label: '反', className: 'bg-amber-100 text-amber-700 ring-amber-200' },
  evidence: { label: '证', className: 'bg-teal-100 text-teal-700 ring-teal-200' },
  arbiter: { label: '裁', className: 'bg-blue-100 text-blue-700 ring-blue-200' },
  final: { label: '结', className: 'bg-slate-900 text-white ring-slate-300' },
  user: { label: '我', className: 'bg-primary text-primary-foreground ring-primary/30' },
  system: { label: '系', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
}

function formatListSection(title: string, items: string[]) {
  const clean = items.map((item) => item.trim()).filter(Boolean)
  if (clean.length === 0) return ''
  return [title, ...clean.map((item) => `- ${item}`)].join('\n')
}

function appendMessageDetail(message: DebateChatMessage, detail: string) {
  const clean = detail.trim()
  if (!clean) return message
  return {
    ...message,
    detail: message.detail ? `${message.detail}\n\n${clean}` : clean,
  }
}

function summarizeToolResult(result: unknown) {
  try {
    const text = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
    return text.length > 900 ? `${text.slice(0, 900)}...` : text
  } catch {
    return String(result)
  }
}

function avatarForMessage(message: DebateChatMessage) {
  if (message.roleId && roleAvatarMap[message.roleId]) return roleAvatarMap[message.roleId]
  if (message.kind === 'user') return roleAvatarMap.user
  if (message.kind === 'arbiter') return roleAvatarMap.arbiter
  if (message.kind === 'final') return roleAvatarMap.final
  if (message.kind === 'status' || message.kind === 'round' || message.kind === 'error') return roleAvatarMap.system
  return roleAvatarMap.system
}

function opinionToMessage(opinion: MultiAgentRoleOpinion): DebateChatMessage {
  const detailParts = [
    opinion.action ? `动作：${opinion.action}` : '',
    formatListSection('结论证据', opinion.evidence),
    formatListSection('风险依据', opinion.risk_notes),
    formatListSection('回应 / 反驳', opinion.rebuttals || []),
  ].filter(Boolean)
  return {
    id: `role-${opinion.round_index}-${opinion.role_id}`,
    kind: 'role',
    roleId: opinion.role_id,
    roundIndex: opinion.round_index,
    speaker: opinion.role_name,
    content: opinion.summary,
    detail: detailParts.join('\n'),
    stance: opinion.stance,
    confidence: opinion.confidence,
  }
}

function arbiterToMessage(arbiter: MultiAgentArbiterSummary): DebateChatMessage {
  const detailParts = [
    formatListSection('支持角色', arbiter.supporting_roles),
    formatListSection('主要分歧', arbiter.disagreements),
    formatListSection('风险提示', arbiter.risk_notes),
    formatListSection('强烈反对', arbiter.strong_opposition),
    arbiter.why_stop ? `停止原因：${arbiter.why_stop}` : '',
  ].filter(Boolean)
  return {
    id: `arbiter-${arbiter.round_index}-${arbiter.convergence_state}-${arbiter.consensus_reached}`,
    kind: 'arbiter',
    roleId: 'arbiter',
    roundIndex: arbiter.round_index,
    speaker: '裁决角色',
    content: arbiter.conclusion,
    detail: detailParts.join('\n\n'),
    confidence: arbiter.confidence,
  }
}

function finalToMessage(conclusion: MultiAgentFinalConclusion): DebateChatMessage {
  const detailParts = [
    conclusion.action ? `动作：${conclusion.action}` : '',
    formatListSection('支持角色', conclusion.supporting_roles),
    formatListSection('主要分歧', conclusion.disagreements),
    formatListSection('风险提示', conclusion.risk_notes),
  ].filter(Boolean)
  return {
    id: `final-${conclusion.recommended_action}-${conclusion.confidence}`,
    kind: 'final',
    roleId: 'final',
    speaker: '最终结论',
    content: conclusion.conclusion,
    detail: detailParts.join('\n\n') || conclusion.action || conclusion.recommended_action,
    confidence: conclusion.confidence,
  }
}

function applyTranscriptEvent(messages: DebateChatMessage[], eventName: string, payload: Record<string, any>) {
  if (eventName === 'status') {
    return [
      ...messages,
      {
        id: `status-${messages.length}-${payload.message || ''}`,
        kind: 'status' as const,
        speaker: '系统',
        content: payload.message || '处理中',
      },
    ]
  }
  if (eventName === 'round_start') {
    return [
      ...messages,
      {
        id: `round-${payload.round_index}-${messages.length}`,
        kind: 'round' as const,
        roundIndex: payload.round_index,
        speaker: '系统',
        content: payload.title || `第 ${payload.round_index} 轮`,
        detail: payload.summary,
      },
    ]
  }
  if (eventName === 'role_start') {
    return [
      ...messages,
      {
        id: payload.message_id,
        kind: 'role' as const,
        roleId: payload.role_id,
        roundIndex: payload.round_index,
        speaker: payload.role_name,
        content: '',
      },
    ]
  }
  if (eventName === 'role_chunk') {
    return messages.map((item) => (
      item.id === payload.message_id ? { ...item, content: `${item.content}${payload.content || ''}` } : item
    ))
  }
  if (eventName === 'tool_call_start') {
    return messages.map((item) => (
      item.id === payload.message_id
        ? appendMessageDetail(item, `调用工具：${payload.tool_name}\n参数：${summarizeToolResult(payload.arguments || {})}`)
        : item
    ))
  }
  if (eventName === 'tool_call_done') {
    return messages.map((item) => (
      item.id === payload.message_id
        ? appendMessageDetail(item, `工具结果：${payload.tool_name}\n${summarizeToolResult(payload.result || {})}`)
        : item
    ))
  }
  if (eventName === 'role_done') {
    const message = opinionToMessage(payload.opinion as MultiAgentRoleOpinion)
    return messages.map((item) => (
      item.id === payload.message_id
        ? { ...message, id: payload.message_id, detail: [item.detail, message.detail].filter(Boolean).join('\n\n') }
        : item
    ))
  }
  if (eventName === 'arbiter') return [...messages, arbiterToMessage(payload as MultiAgentArbiterSummary)]
  if (eventName === 'final') return [...messages, finalToMessage(payload as MultiAgentFinalConclusion)]
  if (eventName === 'error') {
    return [
      ...messages,
      {
        id: `error-${messages.length}-${payload.message || ''}`,
        kind: 'error' as const,
        speaker: '系统',
        content: payload.message || '研判失败',
      },
    ]
  }
  return messages
}

function buildMessagesFromRun(run: MultiAgentRunResponse | null): DebateChatMessage[] {
  if (!run) return []
  if (run.chat_transcript?.length) {
    return run.chat_transcript.reduce<DebateChatMessage[]>(
      (messages, item) => applyTranscriptEvent(messages, item.event, item.payload as Record<string, any>),
      [],
    )
  }
  const messages: DebateChatMessage[] = [
    {
      id: `round-1-${run.run_id}`,
      kind: 'round',
      roundIndex: 1,
      speaker: '系统',
      content: '第 1 轮初始并行分析',
    },
    ...run.initial_role_opinions.map(opinionToMessage),
  ]
  if (run.debate_rounds.length === 0 && run.arbiter_summary) {
    messages.push(arbiterToMessage(run.arbiter_summary))
  }
  for (const round of run.debate_rounds) {
    messages.push({
      id: `round-${round.round_index}-${run.run_id}`,
      kind: 'round',
      roundIndex: round.round_index,
      speaker: '系统',
      content: `第 ${round.round_index} 轮反驳与回应`,
      detail: round.round_summary,
    })
    messages.push(...round.role_opinions.map(opinionToMessage))
    if (round.arbiter_summary) {
      messages.push(arbiterToMessage(round.arbiter_summary))
    }
  }
  messages.push(finalToMessage(run.final_conclusion))
  return messages
}

function DebateChat({ messages, running }: { messages: DebateChatMessage[]; running: boolean }) {
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, running])

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-base">群组辩论</CardTitle>
        {running && <Badge variant="outline">实时生成中</Badge>}
      </CardHeader>
      <CardContent>
        {messages.length === 0 ? (
          <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">
            开始研判后，角色会像群聊一样逐条发言。
          </div>
        ) : (
          <div className="max-h-[640px] space-y-4 overflow-y-auto rounded-xl border bg-slate-50 p-4">
            {messages.map((message) => {
              const isSystem = message.kind === 'status' || message.kind === 'round'
              const isArbiter = message.kind === 'arbiter' || message.kind === 'final'
              const avatar = avatarForMessage(message)
              return (
                <div key={message.id} className={isSystem ? 'flex justify-center' : 'flex justify-start'}>
                  <div className={isSystem ? 'flex max-w-[90%] items-center gap-2' : 'flex max-w-[92%] items-start gap-3'}>
                    <div
                      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1 ${avatar.className}`}
                      title={message.speaker}
                    >
                      {avatar.label}
                    </div>
                    {isSystem ? (
                      <div className="rounded-full border bg-white px-3 py-1.5 text-xs text-muted-foreground">{message.content}</div>
                    ) : (
                      <div
                        className={`rounded-xl border px-4 py-3 shadow-sm ${
                          message.stance ? stanceBubbleMap[message.stance] : isArbiter ? 'border-blue-200 bg-blue-50' : 'bg-white'
                        }`}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold">{message.speaker}</span>
                          {message.roundIndex && <Badge variant="outline">第 {message.roundIndex} 轮</Badge>}
                          {message.stance && <Badge variant="outline">{stanceLabelMap[message.stance]}</Badge>}
                          {typeof message.confidence === 'number' && (
                            <span className="text-xs text-muted-foreground">{message.confidence.toFixed(0)}%</span>
                          )}
                          {message.streaming && <Badge variant="outline">生成中</Badge>}
                          {message.kind === 'final' && <CheckCircle2 className="h-4 w-4 text-blue-600" />}
                        </div>
                        <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{message.content}</div>
                        {message.detail && (
                          <div className="mt-2 whitespace-pre-wrap rounded-lg border bg-white/70 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                            {message.detail}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
            {running && (
              <div className="flex justify-start">
                <div className="flex max-w-[92%] items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
                    …
                  </div>
                  <div className="rounded-xl border bg-white px-4 py-3 text-sm text-muted-foreground shadow-sm">
                    角色正在输入...
                  </div>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RunHistoryItem({
  run,
  active,
  onClick,
  onEdit,
  onDelete,
}: {
  run: MultiAgentRunResponse
  active: boolean
  onClick: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-xl border p-3 text-left transition-colors ${
        active ? 'border-primary bg-primary/5' : 'hover:border-primary/40 hover:bg-muted/30'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 truncate text-sm font-medium">{run.title || run.context_summary.title}</div>
        <div className="flex shrink-0 items-center gap-1" onClick={(event) => event.stopPropagation()}>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onEdit} title="编辑标题">
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onDelete} title="删除记录">
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        </div>
      </div>
    </button>
  )
}

export function MultiAgentWorkbenchPage() {
  const [scene, setScene] = useState<MultiAgentScene>('etf')
  const [messageInput, setMessageInput] = useState('')
  const [usePortfolioContext, setUsePortfolioContext] = useState(true)
  const [portfolios, setPortfolios] = useState<PortfolioWithMarket[]>([])
  const [selectedPortfolioIds, setSelectedPortfolioIds] = useState<number[]>([])
  const [loadingPortfolios, setLoadingPortfolios] = useState(false)
  const [maxDebateRounds, setMaxDebateRounds] = useState(3)
  const [collapseDebateByDefault, setCollapseDebateByDefault] = useState(true)
  const [runs, setRuns] = useState<MultiAgentRunResponse[]>([])
  const [currentRun, setCurrentRun] = useState<MultiAgentRunResponse | null>(null)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [showTranscript, setShowTranscript] = useState(false)
  const [liveContext, setLiveContext] = useState<MultiAgentContextSummary | null>(null)
  const [chatMessages, setChatMessages] = useState<DebateChatMessage[]>([])
  const [editingRun, setEditingRun] = useState<MultiAgentRunResponse | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [savingTitle, setSavingTitle] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<MultiAgentRunResponse | null>(null)
  const [deleting, setDeleting] = useState(false)

  const currentContext = useMemo<MultiAgentContextSummary | null>(() => currentRun?.context_summary ?? liveContext, [currentRun, liveContext])
  const currentInitialOpinions = currentRun?.initial_role_opinions ?? []
  const currentDebateRounds = currentRun?.debate_rounds ?? []
  const currentArbiter = currentRun?.arbiter_summary ?? null

  useEffect(() => {
    setShowTranscript(currentRun ? !currentRun.collapse_debate_by_default : false)
  }, [currentRun?.run_id])

  useEffect(() => {
    if (!running) {
      setChatMessages(buildMessagesFromRun(currentRun))
    }
  }, [currentRun?.run_id, running])

  const loadPortfolios = async () => {
    setLoadingPortfolios(true)
    try {
      const res = await portfolioApi.getList()
      setPortfolios(res.data)
      setSelectedPortfolioIds((prev) => {
        const availableIds = res.data.map((item) => item.id)
        if (prev.length === 0) return availableIds
        return prev.filter((id) => availableIds.includes(id))
      })
    } catch (error: any) {
      console.error('Failed to load portfolios:', error)
      setMessage(error.response?.data?.detail || '加载持仓失败')
    } finally {
      setLoadingPortfolios(false)
    }
  }

  const loadRuns = async () => {
    setLoadingHistory(true)
    setMessage(null)
    try {
      const res = await multiAgentApi.listRuns()
      setRuns(res.data.runs)
      if (!currentRun && res.data.runs.length > 0) {
        const firstRun = res.data.runs[0]
        try {
          const detail = await multiAgentApi.getRun(firstRun.run_id)
          setCurrentRun(detail.data)
          setChatMessages(buildMessagesFromRun(detail.data))
        } catch {
          setCurrentRun(firstRun)
          setChatMessages(buildMessagesFromRun(firstRun))
        }
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
    const continuingRun = currentRun
    if (!continuingRun) {
      setCurrentRun(null)
      setLiveContext(null)
      setChatMessages([])
    }
    const firstMessage = messageInput.trim()
    if (!firstMessage) {
      setMessage('请输入要讨论的问题')
      setRunning(false)
      return
    }
    setChatMessages((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}`,
        kind: 'user',
        roleId: 'user',
        speaker: '用户',
        content: firstMessage,
      },
    ])
    try {
      const continuationPrompt = continuingRun
        ? [
          `这是基于历史研判 #${continuingRun.run_id} 的继续发言。`,
          `上一轮最终结论：${continuingRun.final_conclusion?.conclusion || '无'}`,
          continuingRun.arbiter_summary?.disagreements?.length ? `上一轮主要分歧：${continuingRun.arbiter_summary.disagreements.join('；')}` : '',
          `用户继续发言：${firstMessage}`,
          '请其余智能体基于上述历史结论继续思考，不要当作完全无关的新问题。',
        ].filter(Boolean).join('\n')
        : firstMessage
      const response = await multiAgentApi.streamRun({
        scene,
        question: continuationPrompt,
        use_portfolio_context: usePortfolioContext,
        portfolio_ids: usePortfolioContext ? selectedPortfolioIds : [],
        max_debate_rounds: maxDebateRounds,
        collapse_debate_by_default: collapseDebateByDefault,
      })
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventBlock of events) {
          const lines = eventBlock.split('\n')
          const eventName = lines.find((line) => line.startsWith('event:'))?.replace('event:', '').trim()
          const dataLine = lines.find((line) => line.startsWith('data:'))?.replace('data:', '').trim()
          if (!eventName || !dataLine) continue

          const payload = JSON.parse(dataLine)
          if (eventName === 'status') {
            setChatMessages((prev) => [
              ...prev,
              {
                id: `status-${prev.length}-${Date.now()}`,
                kind: 'status',
                speaker: '系统',
                content: payload.message || '处理中',
              },
            ])
          }
          if (eventName === 'round_start') {
            setChatMessages((prev) => [
              ...prev,
              {
                id: `round-${payload.round_index}-${prev.length}`,
                kind: 'round',
                roundIndex: payload.round_index,
                speaker: '系统',
                content: payload.title || `第 ${payload.round_index} 轮`,
                detail: [
                  payload.summary,
                  Array.isArray(payload.roles) && payload.roles.length ? `本轮角色：${payload.roles.join('、')}` : '',
                ].filter(Boolean).join('\n'),
              },
            ])
          }
          if (eventName === 'context') {
            setLiveContext(payload as MultiAgentContextSummary)
          }
          if (eventName === 'role_start') {
            setChatMessages((prev) => [
              ...prev,
              {
                id: payload.message_id,
                kind: 'role',
                roleId: payload.role_id,
                roundIndex: payload.round_index,
                speaker: payload.role_name,
                content: '',
                streaming: true,
              },
            ])
          }
          if (eventName === 'role_chunk') {
            setChatMessages((prev) => prev.map((item) => (
              item.id === payload.message_id
                ? { ...item, content: `${item.content}${payload.content || ''}`, streaming: true }
                : item
            )))
          }
          if (eventName === 'tool_call_start') {
            setChatMessages((prev) => prev.map((item) => (
              item.id === payload.message_id
                ? appendMessageDetail(
                  item,
                  `调用工具：${payload.tool_name}\n参数：${summarizeToolResult(payload.arguments || {})}`,
                )
                : item
            )))
          }
          if (eventName === 'tool_call_done') {
            setChatMessages((prev) => prev.map((item) => (
              item.id === payload.message_id
                ? appendMessageDetail(
                  item,
                  `工具结果：${payload.tool_name}\n${summarizeToolResult(payload.result || {})}`,
                )
                : item
            )))
          }
          if (eventName === 'role_done') {
            const message = opinionToMessage(payload.opinion as MultiAgentRoleOpinion)
            setChatMessages((prev) => prev.map((item) => (
              item.id === payload.message_id
                ? { ...message, id: payload.message_id, detail: [item.detail, message.detail].filter(Boolean).join('\n\n'), streaming: false }
                : item
            )))
          }
          if (eventName === 'role_opinion') {
            setChatMessages((prev) => [...prev, opinionToMessage(payload as MultiAgentRoleOpinion)])
          }
          if (eventName === 'arbiter') {
            setChatMessages((prev) => [...prev, arbiterToMessage(payload as MultiAgentArbiterSummary)])
          }
          if (eventName === 'final') {
            setChatMessages((prev) => [...prev, finalToMessage(payload as MultiAgentFinalConclusion)])
          }
          if (eventName === 'error') {
            setChatMessages((prev) => [
              ...prev,
              {
                id: `error-${prev.length}-${Date.now()}`,
                kind: 'error',
                speaker: '系统',
                content: payload.message || '研判失败',
              },
            ])
          }
          if (eventName === 'done') {
            const run = payload as MultiAgentRunResponse
            setCurrentRun(run)
            setChatMessages(buildMessagesFromRun(run))
            setShowTranscript(!run.collapse_debate_by_default)
            setRuns((prev) => [run, ...prev.filter((item) => item.run_id !== run.run_id)])
            setMessageInput('')
          }
        }
      }
    } catch (error: any) {
      console.error('Failed to create multi-agent run:', error)
      setMessage(error.response?.data?.detail || error.message || '研判失败')
    } finally {
      setRunning(false)
    }
  }

  const handleLoadRun = async (runId: number) => {
    const localRun = runs.find((item) => item.run_id === runId)
    if (localRun?.chat_transcript?.length) {
      setCurrentRun(localRun)
      setChatMessages(buildMessagesFromRun(localRun))
      setShowTranscript(!localRun.collapse_debate_by_default)
      return
    }
    setMessage(null)
    try {
      const res = await multiAgentApi.getRun(runId)
      setCurrentRun(res.data)
      setChatMessages(buildMessagesFromRun(res.data))
      setShowTranscript(!res.data.collapse_debate_by_default)
    } catch (error: any) {
      console.error('Failed to load run detail:', error)
      setMessage(error.response?.data?.detail || '加载研判详情失败')
    }
  }

  const openEditTitle = (run: MultiAgentRunResponse) => {
    setEditingRun(run)
    setEditingTitle(run.title || run.context_summary.title)
  }

  const handleSaveTitle = async () => {
    if (!editingRun || savingTitle) return
    const title = editingTitle.trim()
    if (!title) {
      setMessage('标题不能为空')
      return
    }

    setSavingTitle(true)
    setMessage(null)
    try {
      const res = await multiAgentApi.updateRun(editingRun.run_id, { title })
      setRuns((prev) => prev.map((item) => item.run_id === res.data.run_id ? res.data : item))
      if (currentRun?.run_id === res.data.run_id) {
        setCurrentRun(res.data)
      }
      setEditingRun(null)
      setEditingTitle('')
    } catch (error: any) {
      console.error('Failed to update run title:', error)
      setMessage(error.response?.data?.detail || '更新标题失败')
    } finally {
      setSavingTitle(false)
    }
  }

  const handleNewDebate = () => {
    setCurrentRun(null)
    setLiveContext(null)
    setChatMessages([])
    setShowTranscript(false)
    setMessageInput('')
    setMessage(null)
  }

  const handleDeleteRun = async () => {
    if (!deleteTarget || deleting) return
    const targetId = deleteTarget.run_id
    setDeleting(true)
    setMessage(null)
    try {
      await multiAgentApi.deleteRun(targetId)
      const nextRuns = runs.filter((item) => item.run_id !== targetId)
      setRuns(nextRuns)
      if (currentRun?.run_id === targetId) {
        setCurrentRun(nextRuns[0] ?? null)
        setChatMessages(buildMessagesFromRun(nextRuns[0] ?? null))
      }
      setDeleteTarget(null)
    } catch (error: any) {
      console.error('Failed to delete run:', error)
      setMessage(error.response?.data?.detail || '删除历史失败')
    } finally {
      setDeleting(false)
    }
  }

  useEffect(() => {
    loadRuns()
    loadPortfolios()
  }, [])

  const activeRunId = currentRun?.run_id ?? runs[0]?.run_id ?? null
  const allPortfolioIds = portfolios.map((item) => item.id)
  const selectedPortfolioCount = selectedPortfolioIds.length
  const allPortfoliosSelected = portfolios.length > 0 && selectedPortfolioCount === portfolios.length
  const togglePortfolio = (id: number) => {
    setSelectedPortfolioIds((prev) => (
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    ))
  }

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
          <Button onClick={handleNewDebate} disabled={running}>
            <Sparkles className="mr-2 h-4 w-4" />
            新建辩论
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
          {usePortfolioContext && (
            <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-medium">引用持仓</div>
                  <div className="text-xs text-muted-foreground">
                    {loadingPortfolios
                      ? '持仓加载中...'
                      : portfolios.length > 0
                        ? `已选择 ${selectedPortfolioCount} / ${portfolios.length} 个持仓`
                        : '当前暂无可引用持仓'}
                  </div>
                </div>
                {portfolios.length > 0 && (
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setSelectedPortfolioIds(allPortfolioIds)}
                      disabled={allPortfoliosSelected}
                    >
                      全选
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => setSelectedPortfolioIds([])}
                      disabled={selectedPortfolioCount === 0}
                    >
                      清空
                    </Button>
                  </div>
                )}
              </div>
              {portfolios.length > 0 && (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {portfolios.map((portfolio) => {
                    const checked = selectedPortfolioIds.includes(portfolio.id)
                    return (
                      <label
                        key={portfolio.id}
                        className={`flex cursor-pointer items-start gap-2 rounded-lg border bg-background px-3 py-2 text-sm transition-colors ${checked ? 'border-primary/50 ring-1 ring-primary/20' : 'hover:border-muted-foreground/40'}`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePortfolio(portfolio.id)}
                          className="mt-1 h-4 w-4 rounded border-muted-foreground/40 accent-primary"
                        />
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{portfolio.etf_code} {portfolio.etf_name || ''}</span>
                          <span className="block text-xs text-muted-foreground">
                            市值 {portfolio.market_value != null ? portfolio.market_value.toFixed(2) : '-'} · 盈亏 {portfolio.pnl_pct != null ? `${portfolio.pnl_pct >= 0 ? '+' : ''}${portfolio.pnl_pct.toFixed(2)}%` : '-'}
                          </span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          )}
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
                  onEdit={() => openEditTitle(run)}
                  onDelete={() => setDeleteTarget(run)}
                />
              ))
            ) : (
              <div className="py-10 text-center text-sm text-muted-foreground">暂无历史记录</div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <ContextSummary summary={currentContext} run={currentRun} />

          <DebateChat messages={chatMessages} running={running} />

          <Card>
            <CardContent className="pt-4">
              <div className="flex flex-col gap-3 sm:flex-row">
                <textarea
                  value={messageInput}
                  onChange={(event) => setMessageInput(event.target.value)}
                  placeholder={currentRun ? '继续追问、补充观点或反驳某个角色...' : '输入你的首个问题，发起多智能体研判...'}
                  className="min-h-20 flex-1 rounded-lg border bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus:ring-1 focus:ring-primary"
                  disabled={running}
                />
                <Button onClick={handleRun} disabled={running || !messageInput.trim()} className="sm:self-end">
                  <Sparkles className="mr-2 h-4 w-4" />
                  {running ? '研判中...' : currentRun ? '继续发言' : '发起研判'}
                </Button>
              </div>
            </CardContent>
          </Card>


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

      <Dialog open={!!editingRun} onOpenChange={(open) => {
        if (!open && !savingTitle) {
          setEditingRun(null)
          setEditingTitle('')
        }
      }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>编辑历史标题</DialogTitle>
          </DialogHeader>
          <Input
            value={editingTitle}
            onChange={(event) => setEditingTitle(event.target.value)}
            maxLength={120}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingRun(null)} disabled={savingTitle}>取消</Button>
            <Button onClick={handleSaveTitle} disabled={savingTitle || !editingTitle.trim()}>
              {savingTitle ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open && !deleting) {
            setDeleteTarget(null)
          }
        }}
        title="删除历史记录"
        description={deleteTarget ? `确认删除“${deleteTarget.title || deleteTarget.context_summary.title}”吗？此操作不可撤销。` : ''}
        confirmText="确认删除"
        onConfirm={handleDeleteRun}
        loading={deleting}
        variant="destructive"
      />
    </div>
  )
}

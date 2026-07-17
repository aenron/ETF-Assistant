import { type ComponentPropsWithoutRef, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Bot, ChevronDown, ChevronLeft, Copy, Loader2, MemoryStick, MessageCircle, Plus, RotateCcw, Search, Send, Trash2, UserRoundCheck, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

import { assistantApi, portfolioApi, type AssistantMessage, type AssistantSession, type AssistantStreamPhase, type PortfolioWithMarket } from '@/services/api'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from './ConfirmDialog'
import { compareBeijingTimeDesc, formatBeijingTime } from '@/utils/time'

const ASSISTANT_PHASE_TEXT: Record<AssistantStreamPhase, string> = {
  preparing: '正在准备请求...',
  calling_model: '正在调用模型...',
  searching: '正在搜索资料...',
  generating: '正在生成回答...',
}

function getAssistantPhaseText(message: AssistantMessage) {
  if (message.role !== 'assistant' || message.status !== 'streaming') return null
  return ASSISTANT_PHASE_TEXT[message.stream_phase || 'calling_model']
}

function normalizeLooseMarkdownHeadings(content: string) {
  const lines = content.split('\n')
  let inFence = false

  return lines.map((line) => {
    if (line.trimStart().startsWith('```')) {
      inFence = !inFence
      return line
    }
    if (inFence) return line

    return line.replace(/([^\n])\s+(#{1,6})\s+([^#\n][^\n]*)/g, (_match, before, hashes, title) => {
      return `${before}\n\n${hashes} ${title.trim()}`
    })
  }).join('\n')
}

function normalizeStreamingMarkdown(content: string) {
  const normalized = normalizeLooseMarkdownHeadings(content)
  const fenceMatches = normalized.match(/```/g)
  if (fenceMatches && fenceMatches.length % 2 === 1) {
    return `${normalized}\n` + "```"
  }
  return normalized
}

function CodeBlock({ className, children, ...props }: ComponentPropsWithoutRef<'code'>) {
  const match = /language-([\w-]+)/.exec(className || '')
  const language = match?.[1]
  const codeText = String(children || '').replace(/\n$/, '')

  if (!className?.includes('language-')) {
    return (
      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-emerald-700" {...props}>
        {children}
      </code>
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-950 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-[11px] text-slate-400">
        <span>{language || 'code'}</span>
        <button
          type="button"
          onClick={() => navigator.clipboard?.writeText(codeText)}
          className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100"
          title="复制代码"
        >
          <Copy className="h-3 w-3" />
          复制
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-3 text-[12px] leading-6 text-slate-100">
        <code className={className} {...props}>{children}</code>
      </pre>
    </div>
  )
}

function renderAssistantContent(content: string) {
  if (!content.trim()) return null

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        h1: ({ children }) => <h1 className="mt-1 text-base font-semibold leading-7 text-slate-950 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="mt-3 border-b border-slate-100 pb-1 text-sm font-semibold leading-6 text-slate-950 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="mt-3 text-sm font-semibold leading-6 text-slate-900 first:mt-0">{children}</h3>,
        p: ({ children }) => <p className="leading-7 text-slate-700">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-slate-950">{children}</strong>,
        em: ({ children }) => <em className="text-slate-700">{children}</em>,
        a: ({ href, children }) => (
          <a
            href={href || '#'}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-emerald-700 underline decoration-emerald-300 underline-offset-2 transition-colors hover:text-emerald-900"
          >
            {children}
          </a>
        ),
        ul: ({ children }) => <ul className="my-2 space-y-1.5 pl-5 text-slate-700 marker:text-emerald-500">{children}</ul>,
        ol: ({ children }) => <ol className="my-2 space-y-1.5 pl-5 text-slate-700 marker:font-semibold marker:text-emerald-700">{children}</ol>,
        li: ({ children }) => <li className="pl-1 leading-6">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-emerald-300 bg-emerald-50/70 px-3 py-2 text-[13px] text-slate-700">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-3 border-slate-200" />,
        code: CodeBlock,
        pre: ({ children }) => <>{children}</>,
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full border-collapse text-left text-[12px]">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-slate-50 text-slate-600">{children}</thead>,
        tbody: ({ children }) => <tbody className="divide-y divide-slate-100 bg-white">{children}</tbody>,
        th: ({ children }) => <th className="whitespace-nowrap px-3 py-2 font-semibold text-slate-700">{children}</th>,
        td: ({ children }) => <td className="whitespace-nowrap px-3 py-2 text-slate-700">{children}</td>,
      }}
    >
      {normalizeStreamingMarkdown(content)}
    </ReactMarkdown>
  )
}

export function FloatingAssistant() {
  const [open, setOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [showMobileSessions, setShowMobileSessions] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [sending, setSending] = useState(false)
  const [sessions, setSessions] = useState<AssistantSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [draft, setDraft] = useState('')
  const [sessionToDelete, setSessionToDelete] = useState<AssistantSession | null>(null)
  const [deletingSession, setDeletingSession] = useState(false)
  const [includePortfolioContext, setIncludePortfolioContext] = useState(true)
  const [portfolioOptions, setPortfolioOptions] = useState<PortfolioWithMarket[]>([])
  const [selectedPortfolioIds, setSelectedPortfolioIds] = useState<number[]>([])
  const [loadingPortfolios, setLoadingPortfolios] = useState(false)
  const [portfolioSelectorOpen, setPortfolioSelectorOpen] = useState(false)
  const [portfolioSearch, setPortfolioSearch] = useState('')
  const [assistantError, setAssistantError] = useState<string | null>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const portfolioSelectionInitializedRef = useRef(false)
  const subscribedMessageIdsRef = useRef<Set<number>>(new Set())
  const messagesContainerRef = useRef<HTMLDivElement | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const waitForPaint = () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()))

  const updateStickToBottom = () => {
    const container = messagesContainerRef.current
    if (!container) return
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight
    setStickToBottom(distanceToBottom < 96)
  }

  const scrollMessagesToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior })
    setStickToBottom(true)
  }

  const fetchPortfolios = async () => {
    setLoadingPortfolios(true)
    try {
      const res = await portfolioApi.getList()
      const nextPortfolios = res.data || []
      const availableIds = nextPortfolios.map((item) => item.id)
      setPortfolioOptions(nextPortfolios)
      setSelectedPortfolioIds((prev) => {
        if (!portfolioSelectionInitializedRef.current) {
          portfolioSelectionInitializedRef.current = true
          return availableIds
        }
        return prev.filter((id) => availableIds.includes(id))
      })
    } catch (error) {
      console.error('Failed to fetch assistant portfolios:', error)
      setAssistantError('持仓列表加载失败，请稍后重试')
    } finally {
      setLoadingPortfolios(false)
    }
  }

  const formatMoney = (value: number | null | undefined) => {
    if (value === null || value === undefined || !Number.isFinite(value)) return '--'
    return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  const togglePortfolioSelection = (portfolioId: number) => {
    setSelectedPortfolioIds((prev) => (
      prev.includes(portfolioId) ? prev.filter((id) => id !== portfolioId) : [...prev, portfolioId]
    ))
  }

  const fetchSessions = async (preferredSessionId?: number | null) => {
    setLoadingSessions(true)
    try {
      const res = await assistantApi.listSessions()
      const nextSessions = res.data.sessions || []
      setSessions(nextSessions)
      if (preferredSessionId) {
        setActiveSessionId(preferredSessionId)
      } else if (nextSessions.length > 0) {
        setActiveSessionId((current) =>
          current && nextSessions.some((item) => item.id === current) ? current : nextSessions[0].id,
        )
      } else {
        setActiveSessionId(null)
        setMessages([])
      }
    } catch (error) {
      console.error('Failed to fetch assistant sessions:', error)
      setAssistantError('会话列表加载失败，请稍后重试')
    } finally {
      setLoadingSessions(false)
    }
  }

  const fetchHistory = async (sessionId: number) => {
    setLoadingHistory(true)
    try {
      const res = await assistantApi.getHistory(sessionId)
      setMessages(res.data.messages || [])
      setActiveSessionId(res.data.session.id)
      setSessions((prev) => {
        const exists = prev.some((item) => item.id === res.data.session.id)
        const next = exists ? prev.map((item) => item.id === res.data.session.id ? res.data.session : item) : [res.data.session, ...prev]
        return next.sort((a, b) => compareBeijingTimeDesc(a.updated_at, b.updated_at))
      })
    } catch (error) {
      console.error('Failed to fetch assistant history:', error)
      setAssistantError('历史消息加载失败，请稍后重试')
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 767px)')
    const syncViewport = (event?: MediaQueryListEvent) => {
      const matches = event ? event.matches : mediaQuery.matches
      setIsMobile(matches)
      if (!matches) {
        setShowMobileSessions(false)
      }
    }

    syncViewport()
    mediaQuery.addEventListener('change', syncViewport)
    return () => mediaQuery.removeEventListener('change', syncViewport)
  }, [])

  useEffect(() => {
    if (open) {
      fetchSessions()
      fetchPortfolios()
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      setShowMobileSessions(false)
    } else if (isMobile) {
      setShowMobileSessions(true)
    }
  }, [open, isMobile])

  useEffect(() => {
    if (open && activeSessionId) {
      fetchHistory(activeSessionId)
    }
  }, [open, activeSessionId])

  useEffect(() => {
    if (!open) return
    const streamingMessage = messages.find((item) => item.role === 'assistant' && item.status === 'streaming')
    if (streamingMessage) {
      subscribeAssistantMessage(streamingMessage.id)
    }
  }, [open, messages])

  useEffect(() => {
    if (open && stickToBottom) {
      scrollMessagesToBottom('smooth')
    }
  }, [messages, open, sending, stickToBottom])

  const handleCreateSession = async () => {
    try {
      setAssistantError(null)
      const res = await assistantApi.createSession()
      setSessions((prev) => [res.data, ...prev])
      setActiveSessionId(res.data.id)
      setMessages([])
    } catch (error) {
      console.error('Failed to create assistant session:', error)
      setAssistantError('创建会话失败，请稍后重试')
    }
  }

  const handleDeleteSession = async () => {
    if (!sessionToDelete || deletingSession) return

    setDeletingSession(true)
    try {
      setAssistantError(null)
      await assistantApi.deleteSession(sessionToDelete.id)
      const nextSessions = sessions.filter((item) => item.id !== sessionToDelete.id)
      setSessions(nextSessions)
      if (activeSessionId === sessionToDelete.id) {
        const nextId = nextSessions[0]?.id ?? null
        setActiveSessionId(nextId)
        if (!nextId) setMessages([])
      }
      setSessionToDelete(null)
    } catch (error) {
      console.error('Failed to delete assistant session:', error)
      setAssistantError('删除会话失败，请稍后重试')
    } finally {
      setDeletingSession(false)
    }
  }


  const consumeStreamResponse = async (
    response: Response,
    assistantMessageId: number,
    tempAssistantId?: number,
    retryUserId?: number | null,
  ) => {
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentAssistantId = assistantMessageId

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
        if (eventName === 'meta') {
          setSessions((prev) => {
            const exists = prev.some((item) => item.id === payload.session.id)
            const next = exists ? prev.map((item) => item.id === payload.session.id ? payload.session : item) : [payload.session, ...prev]
            return next.sort((a, b) => compareBeijingTimeDesc(a.updated_at, b.updated_at))
          })
          setActiveSessionId(payload.session.id)
          if (payload.assistant_message) {
            currentAssistantId = payload.assistant_message.id
            subscribedMessageIdsRef.current.add(currentAssistantId)
          }
          setMessages((prev) => {
            const next = [...prev]
            const userIndex = next.findIndex((item) => item.id === retryUserId)
            if (userIndex >= 0 && payload.user_message) next[userIndex] = payload.user_message
            if (payload.assistant_message && tempAssistantId) {
              const assistantIndex = next.findIndex((item) => item.id === tempAssistantId)
              if (assistantIndex >= 0) next[assistantIndex] = payload.assistant_message
              else if (!next.some((item) => item.id === payload.assistant_message.id)) next.push(payload.assistant_message)
            }
            return next
          })
        }

        if (eventName === 'snapshot' && payload.assistant_message) {
          currentAssistantId = payload.assistant_message.id
          setMessages((prev) => prev.map((item) => item.id === currentAssistantId ? payload.assistant_message : item))
        }

        if (eventName === 'phase') {
          setMessages((prev) => prev.map((item) => item.id === currentAssistantId ? { ...item, stream_phase: payload.phase, status: 'streaming' } : item))
        }

        if (eventName === 'chunk') {
          setMessages((prev) => prev.map((item) => item.id === currentAssistantId ? { ...item, content: `${item.content}${payload.content}`, status: 'streaming', stream_phase: 'generating' } : item))
          await waitForPaint()
        }

        if (eventName === 'done' && payload.assistant_message) {
          currentAssistantId = payload.assistant_message.id
          subscribedMessageIdsRef.current.delete(currentAssistantId)
          if (payload.session) {
            setSessions((prev) => {
              const exists = prev.some((item) => item.id === payload.session.id)
              const next = exists ? prev.map((item) => item.id === payload.session.id ? payload.session : item) : [payload.session, ...prev]
              return next.sort((a, b) => compareBeijingTimeDesc(a.updated_at, b.updated_at))
            })
          }
          setMessages((prev) => prev.map((item) => item.id === currentAssistantId || item.id === tempAssistantId ? { ...payload.assistant_message, stream_phase: null } : item))
        }
      }
    }
  }

  const subscribeAssistantMessage = async (messageId: number) => {
    if (subscribedMessageIdsRef.current.has(messageId)) return
    subscribedMessageIdsRef.current.add(messageId)
    setSending(true)
    try {
      const response = await assistantApi.subscribeStream(messageId)
      await consumeStreamResponse(response, messageId)
    } catch (error) {
      console.error('Failed to subscribe assistant stream:', error)
      subscribedMessageIdsRef.current.delete(messageId)
      if (activeSessionId) fetchHistory(activeSessionId)
    } finally {
      setSending(false)
    }
  }

  const sendMessage = async (content: string, clearDraft = false, retryMessage?: AssistantMessage) => {
    const message = content.trim()
    if (!message || sending) return

    setAssistantError(null)
    setStickToBottom(true)

    let sessionId = activeSessionId
    if (!sessionId) {
      try {
        const res = await assistantApi.createSession()
        sessionId = res.data.id
        setSessions((prev) => [res.data, ...prev])
        setActiveSessionId(res.data.id)
      } catch (error) {
        console.error('Failed to create session before sending:', error)
        setAssistantError('创建会话失败，请稍后重试')
        return
      }
    }

    setSending(true)
    const tempUserId = retryMessage ? null : Date.now()
    const tempAssistantId = Date.now() + 1
    const now = new Date().toISOString()
    setMessages((prev) => {
      if (!retryMessage) {
        return [
          ...prev,
          { id: tempUserId as number, role: 'user', content: message, created_at: now },
          { id: tempAssistantId, role: 'assistant', content: '', status: 'streaming', stream_phase: 'preparing', created_at: now },
        ]
      }

      const retryIndex = prev.findIndex((item) => item.id === retryMessage.id)
      const keptMessages = retryIndex >= 0 ? prev.slice(0, retryIndex + 1) : prev
      return [
        ...keptMessages,
        { id: tempAssistantId, role: 'assistant', content: '', status: 'streaming', stream_phase: 'preparing', created_at: now },
      ]
    })
    if (clearDraft) {
      setDraft('')
    }

    try {
      const portfolioIdsForRequest = includePortfolioContext && portfolioSelectionInitializedRef.current ? selectedPortfolioIds : undefined
      const response = await assistantApi.streamChat(message, sessionId, retryMessage?.id, includePortfolioContext, portfolioIdsForRequest)
      await consumeStreamResponse(response, tempAssistantId, tempAssistantId, retryMessage?.id ?? tempUserId)
    } catch (error) {
      console.error('Failed to send assistant message:', error)
      if (retryMessage && sessionId) {
        fetchHistory(sessionId)
      } else {
        setMessages((prev) => prev.filter((item) => item.id !== tempUserId && item.id !== tempAssistantId))
      }
      setAssistantError('发送消息失败，请稍后重试')
    } finally {
      setSending(false)
    }
  }

  const handleSend = async () => {
    await sendMessage(draft, true)
  }

  const handleResend = async (message: AssistantMessage) => {
    await sendMessage(message.content, false, message)
  }

  const activeSession = sessions.find((item) => item.id === activeSessionId)
  const streamingMessage = messages.find((item) => item.role === 'assistant' && item.status === 'streaming')
  const currentPhaseText = streamingMessage ? getAssistantPhaseText(streamingMessage) : null
  const showStandaloneSending = sending && !streamingMessage
  const normalizedPortfolioSearch = portfolioSearch.trim().toLowerCase()
  const filteredPortfolios = portfolioOptions.filter((portfolio) => {
    if (!normalizedPortfolioSearch) return true
    return `${portfolio.etf_code} ${portfolio.etf_name || ''}`.toLowerCase().includes(normalizedPortfolioSearch)
  })
  const portfolioGroups = filteredPortfolios.reduce<Record<string, PortfolioWithMarket[]>>((groups, portfolio) => {
    const typeLabel = portfolio.asset_type === 'stock' ? '股票' : portfolio.asset_type === 'otc_fund' ? '场外基金' : portfolio.asset_type === 'money_fund' ? '货币基金' : portfolio.asset_type === 'cash' ? '现金' : '场内基金/ETF'
    groups[typeLabel] = [...(groups[typeLabel] || []), portfolio]
    return groups
  }, {})

  return (
    <>
      {open && (
        <div className={`${isMobile ? 'fixed inset-0 z-50 flex flex-col bg-white' : 'fixed bottom-24 right-6 top-6 z-50 flex w-[min(860px,calc(100vw-48px))] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/15'}`}>
          <div className={`${isMobile ? `${showMobileSessions ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col bg-slate-50` : 'flex w-[260px] flex-col border-r border-slate-200 bg-slate-50'}`}>
            <div className="border-b border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                      <MemoryStick className="h-4 w-4" />
                    </span>
                    智能体助手
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">会话记忆与持仓上下文</div>
                </div>
                <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-500 hover:bg-slate-100 hover:text-slate-900" onClick={() => setOpen(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <Button size="sm" variant="outline" className="mt-3 h-8 w-full justify-center border-slate-200 bg-white text-slate-700 hover:bg-slate-50" onClick={handleCreateSession}>
                <Plus className="mr-2 h-4 w-4" />
                新建会话
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
              {loadingSessions && <div className="flex items-center justify-center py-8 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载会话中...</div>}
              {!loadingSessions && sessions.length === 0 && <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-4 text-xs text-muted-foreground">暂无会话，点击上方新建。</div>}
              <div className="space-y-1.5">
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={`group relative rounded-lg border transition-colors ${activeSessionId === session.id ? 'border-emerald-200 bg-white shadow-sm shadow-emerald-900/5' : 'border-transparent hover:border-slate-200 hover:bg-white'}`}
                  >
                    {activeSessionId === session.id && <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-emerald-500" />}
                    <button
                      type="button"
                      onClick={() => {
                        setActiveSessionId(session.id)
                        if (isMobile) {
                          setShowMobileSessions(false)
                        }
                      }}
                      className="block w-full px-3 py-2.5 pr-10 text-left"
                    >
                      <div className="truncate text-[13px] font-medium text-slate-900">{session.title}</div>
                      <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{session.last_message_preview || '暂无消息'}</div>
                      <div className="mt-2 text-[10px] text-slate-400">{formatBeijingTime(session.updated_at, {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}</div>
                    </button>
                    <button
                      type="button"
                      className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 focus:bg-red-50 focus:text-red-600"
                      title="删除会话"
                      onClick={(event) => {
                        event.stopPropagation()
                        setSessionToDelete(session)
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className={`${isMobile && showMobileSessions ? 'hidden' : 'flex'} min-h-0 flex-1 flex-col bg-white`}>
            <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
              <div className="min-w-0">
                {isMobile && (
                  <button
                    className="mb-2 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900"
                    onClick={() => setShowMobileSessions(true)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5 rotate-180" />
                    会话列表
                  </button>
                )}
                <div className="truncate text-sm font-semibold text-slate-950">
                  {activeSession?.title || '当前会话'}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span>{includePortfolioContext ? `已引用 ${selectedPortfolioIds.length} 个持仓` : '未引用持仓'}</span>
                  <span className="h-1 w-1 rounded-full bg-slate-300" />
                  <span>会参考该会话上下文</span>
                  {currentPhaseText && (
                    <>
                      <span className="h-1 w-1 rounded-full bg-slate-300" />
                      <span className="inline-flex items-center gap-1 text-emerald-700"><Loader2 className="h-3 w-3 animate-spin" />{currentPhaseText}</span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {activeSessionId && (
                  <button
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                    title="删除会话"
                    onClick={() => {
                      if (activeSession) {
                        setSessionToDelete(activeSession)
                      }
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
                <button
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-900"
                  title="关闭"
                  onClick={() => setOpen(false)}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div
              ref={messagesContainerRef}
              onScroll={updateStickToBottom}
              className="relative min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50 px-5 py-5"
            >
              {assistantError && (
                <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1">{assistantError}</span>
                  <button type="button" className="text-amber-700 hover:text-amber-900" onClick={() => setAssistantError(null)}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              {loadingHistory && <div className="flex items-center justify-center py-10 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载对话中...</div>}
              {!loadingHistory && messages.length === 0 && (
                <div className="mx-auto mt-6 max-w-xl rounded-xl border border-dashed border-slate-200 bg-white px-5 py-5 text-sm text-slate-600 shadow-sm">
                  <div className="mb-3 flex items-center gap-2 font-medium text-slate-900">
                    <Bot className="h-4 w-4 text-emerald-600" />
                    开始一次投研对话
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {[
                      '我当前仓位是否太高？',
                      '哪些持仓需要优先减仓？',
                      '结合行情给我今日操作建议',
                    ].map((question) => (
                      <button
                        key={question}
                        type="button"
                        onClick={() => setDraft(question)}
                        className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs leading-5 text-slate-600 transition-colors hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-800"
                      >
                        {question}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {!loadingHistory && messages.map((message) => {
                const phaseText = getAssistantPhaseText(message)
                return (
                  <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`flex max-w-[94%] flex-col ${message.role === 'user' ? 'items-end' : 'items-start'} md:max-w-[88%]`}>
                      <div className={`rounded-xl px-3.5 py-3 text-sm ${message.role === 'user' ? 'bg-slate-900 text-white shadow-sm shadow-slate-900/10' : 'border border-slate-200 bg-white text-slate-800 shadow-sm shadow-slate-900/5'}`}>
                        <div className={`${message.role === 'assistant' ? 'space-y-3 text-[13px]' : 'whitespace-pre-wrap leading-relaxed'}`}>
                          {message.role === 'assistant' ? renderAssistantContent(message.content) : message.content}
                          {phaseText && (
                            <div className="flex items-center gap-2 border-t border-slate-100 pt-2 text-xs text-slate-500">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              {phaseText}
                            </div>
                          )}
                        </div>
                      </div>
                      <div className={`mt-1.5 flex items-center gap-2 text-[10px] ${message.role === 'user' ? 'text-slate-400' : 'text-slate-400'}`}>
                        <span>{formatBeijingTime(message.created_at, {
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}</span>
                        {message.role === 'user' && (
                          <button
                            type="button"
                            onClick={() => handleResend(message)}
                            disabled={sending}
                            title="重发这条消息"
                            className="inline-flex h-5 items-center gap-1 rounded px-1.5 text-[10px] text-slate-400 transition-colors hover:bg-white hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            <RotateCcw className="h-3 w-3" />
                            重发
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
              {showStandaloneSending && (
                <div className="flex justify-start">
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-muted-foreground shadow-sm">
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在准备请求...
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
              {!stickToBottom && (
                <button
                  type="button"
                  onClick={() => scrollMessagesToBottom()}
                  className="sticky bottom-2 left-1/2 z-10 mx-auto flex -translate-x-0 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 shadow-lg shadow-slate-900/10 transition-colors hover:border-emerald-200 hover:text-emerald-700"
                >
                  <ChevronDown className="h-3.5 w-3.5" />
                  回到底部
                </button>
              )}
            </div>

            <div className="border-t border-slate-200 bg-white px-4 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
              <div className="mb-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() => includePortfolioContext && setPortfolioSelectorOpen((value) => !value)}
                    className="flex min-w-0 items-center gap-2 text-left text-xs text-slate-600 disabled:cursor-default"
                    disabled={!includePortfolioContext}
                  >
                    <UserRoundCheck className={`h-4 w-4 shrink-0 ${includePortfolioContext ? 'text-emerald-600' : 'text-slate-400'}`} />
                    <span className="truncate">
                      {includePortfolioContext ? `引用持仓 ${selectedPortfolioIds.length}/${portfolioOptions.length}` : '不引用持仓信息'}
                    </span>
                  </button>
                  <div className="flex items-center gap-2">
                    {includePortfolioContext && (
                      <button
                        type="button"
                        onClick={() => setPortfolioSelectorOpen((value) => !value)}
                        className="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
                      >
                        {portfolioSelectorOpen ? '收起' : '选择'}
                      </button>
                    )}
                    <button
                      type="button"
                      role="switch"
                      aria-checked={includePortfolioContext}
                      onClick={() => setIncludePortfolioContext((value) => !value)}
                      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${includePortfolioContext ? 'bg-emerald-600' : 'bg-slate-300'}`}
                      title="控制智能体是否引用当前持仓和账户概况"
                    >
                      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${includePortfolioContext ? 'translate-x-5' : 'translate-x-0.5'}`} />
                    </button>
                  </div>
                </div>

                {includePortfolioContext && portfolioSelectorOpen && (
                  <div className="mt-2 border-t border-slate-200 pt-2">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-[11px] text-slate-500">{loadingPortfolios ? '加载持仓中...' : `已选择 ${selectedPortfolioIds.length} / ${portfolioOptions.length}`}</span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => setSelectedPortfolioIds(portfolioOptions.map((item) => item.id))}
                          className="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
                        >
                          全选
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedPortfolioIds([])}
                          className="rounded-md px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-white hover:text-slate-800"
                        >
                          清空
                        </button>
                      </div>
                    </div>
                    <div className="mb-2 flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1.5">
                      <Search className="h-3.5 w-3.5 text-slate-400" />
                      <input
                        value={portfolioSearch}
                        onChange={(event) => setPortfolioSearch(event.target.value)}
                        placeholder="搜索代码或名称"
                        className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400"
                      />
                      {portfolioSearch && (
                        <button type="button" onClick={() => setPortfolioSearch('')} className="text-slate-400 hover:text-slate-700">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <div className="max-h-36 space-y-2 overflow-y-auto pr-1">
                      {!loadingPortfolios && portfolioOptions.length === 0 && (
                        <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">暂无可引用持仓</div>
                      )}
                      {!loadingPortfolios && portfolioOptions.length > 0 && filteredPortfolios.length === 0 && (
                        <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">没有匹配的持仓</div>
                      )}
                      {Object.entries(portfolioGroups).map(([groupName, portfolios]) => (
                        <div key={groupName}>
                          <div className="mb-1 px-1 text-[10px] font-medium text-slate-400">{groupName}</div>
                          <div className="grid gap-1 sm:grid-cols-2">
                            {portfolios.map((portfolio) => (
                              <label
                                key={portfolio.id}
                                className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-white"
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedPortfolioIds.includes(portfolio.id)}
                                  onChange={() => togglePortfolioSelection(portfolio.id)}
                                  className="h-3.5 w-3.5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                                />
                                <span className="min-w-0 flex-1 truncate text-slate-700">
                                  {portfolio.etf_code} {portfolio.etf_name || ''}
                                </span>
                                <span className="shrink-0 tabular-nums text-slate-500">{formatMoney(portfolio.market_value)}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              <div className="rounded-xl border border-slate-200 bg-white p-2 shadow-sm shadow-slate-900/5">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      handleSend()
                    }
                  }}
                  placeholder="询问持仓、仓位、调仓思路或风险点..."
                  className="max-h-36 min-h-[72px] w-full resize-none border-0 bg-transparent px-2 py-1 text-sm leading-6 outline-none placeholder:text-slate-400"
                />
                <div className="mt-1 flex items-center justify-between gap-2 px-1">
                  <span className="text-[11px] text-slate-400">Enter 发送，Shift+Enter 换行</span>
                  <Button size="icon" className="h-8 w-8 rounded-lg" onClick={handleSend} disabled={sending || !draft.trim()} title="发送">
                    {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!sessionToDelete}
        onOpenChange={(open) => {
          if (!open && !deletingSession) {
            setSessionToDelete(null)
          }
        }}
        title="删除当前会话"
        description={sessionToDelete ? `确认删除会话“${sessionToDelete.title}”吗？该会话的历史消息将一并删除。` : ''}
        confirmText="确认删除"
        onConfirm={handleDeleteSession}
        loading={deletingSession}
        variant="destructive"
      />

      <button
        onClick={() => setOpen((value) => !value)}
        className="fixed bottom-4 right-4 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-slate-900 via-slate-800 to-emerald-600 text-white shadow-2xl shadow-slate-900/25 transition-transform hover:scale-105 md:bottom-6 md:right-6 md:h-16 md:w-16"
        title="打开智能体助手"
      >
        {open ? <X className="h-6 w-6 md:h-7 md:w-7" /> : <MessageCircle className="h-6 w-6 md:h-7 md:w-7" />}
      </button>

      {!open && (
        <div className="fixed bottom-7 right-24 z-40 hidden rounded-full border border-emerald-200 bg-white/95 px-3 py-1.5 text-xs text-slate-600 shadow-lg backdrop-blur md:block">
          <span className="flex items-center gap-1.5">
            <Bot className="h-3.5 w-3.5 text-emerald-600" />
            智能体助手
          </span>
        </div>
      )}
    </>
  )
}

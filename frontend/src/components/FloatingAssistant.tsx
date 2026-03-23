import { useEffect, useRef, useState } from 'react'
import { Bot, ChevronLeft, Loader2, MemoryStick, MessageCircle, Plus, Send, Trash2, X } from 'lucide-react'

import { assistantApi, type AssistantMessage, type AssistantSession } from '@/services/api'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from './ConfirmDialog'

type AssistantSegment =
  | { type: 'markdown'; content: string }
  | { type: 'code'; content: string; language: string | null }

function splitAssistantSegments(content: string): AssistantSegment[] {
  const segments: AssistantSegment[] = []
  const codeBlockRegex = /```([a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = codeBlockRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'markdown', content: content.slice(lastIndex, match.index) })
    }
    segments.push({
      type: 'code',
      language: match[1] || null,
      content: match[2].replace(/\n$/, ''),
    })
    lastIndex = codeBlockRegex.lastIndex
  }

  if (lastIndex < content.length) {
    segments.push({ type: 'markdown', content: content.slice(lastIndex) })
  }

  return segments.filter((segment) => segment.content.trim())
}

function renderInline(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*.*?\*\*)/g).filter(Boolean)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${part}-${index}`} className="font-semibold text-slate-900">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={`${part}-${index}`} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-emerald-700">
          {part.slice(1, -1)}
        </code>
      )
    }
    return <span key={`${part}-${index}`}>{part}</span>
  })
}

function renderMarkdownBlock(block: string, keyPrefix: string) {
  const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
  const isList = lines.every((line) => /^([-*]|\d+\.)\s+/.test(line))
  const headingMatch = lines.length === 1 ? lines[0].match(/^(#{1,3})\s+(.+)$/) : null
  const quoteBlock = lines.every((line) => line.startsWith('>'))

  if (headingMatch) {
    const level = headingMatch[1].length
    const title = headingMatch[2]
    const className =
      level === 1 ? 'text-base font-semibold text-slate-900' :
      level === 2 ? 'text-sm font-semibold text-slate-900' :
      'text-sm font-medium text-slate-800'
    return <div key={keyPrefix} className={className}>{renderInline(title)}</div>
  }

  if (quoteBlock) {
    return (
      <div key={keyPrefix} className="border-l-2 border-emerald-300 bg-emerald-50/60 px-3 py-2 text-[13px] text-slate-700">
        {lines.map((line, index) => (
          <p key={`${keyPrefix}-quote-${index}`} className="leading-6">
            {renderInline(line.replace(/^>\s?/, ''))}
          </p>
        ))}
      </div>
    )
  }

  if (isList) {
    return (
      <div key={keyPrefix} className="space-y-2">
        {lines.map((line, index) => {
          const text = line.replace(/^([-*]|\d+\.)\s+/, '')
          const ordered = /^\d+\./.test(line)
          return (
            <div key={`${keyPrefix}-line-${index}`} className="flex gap-2 leading-6">
              {ordered ? (
                <span className="min-w-5 text-right text-xs font-semibold text-emerald-700">
                  {line.match(/^(\d+)\./)?.[1]}.
                </span>
              ) : (
                <span className="mt-2 h-1.5 w-1.5 rounded-full bg-emerald-500" />
              )}
              <div>{renderInline(text)}</div>
            </div>
          )
        })}
      </div>
    )
  }

  if (lines.length === 1) {
    return <p key={keyPrefix} className="leading-7">{renderInline(lines[0])}</p>
  }

  return (
    <div key={keyPrefix} className="space-y-1.5">
      {lines.map((line, index) => (
        <p key={`${keyPrefix}-line-${index}`} className="leading-7">{renderInline(line)}</p>
      ))}
    </div>
  )
}

function renderAssistantContent(content: string) {
  return splitAssistantSegments(content).flatMap((segment, segmentIndex) => {
    if (segment.type === 'code') {
      return (
        <div key={`segment-${segmentIndex}`} className="overflow-hidden rounded-xl border border-slate-200 bg-slate-950 shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-[11px] text-slate-400">
            <span>{segment.language || 'code'}</span>
          </div>
          <pre className="overflow-x-auto px-3 py-3 text-[12px] leading-6 text-slate-100">
            <code>{segment.content}</code>
          </pre>
        </div>
      )
    }

    return segment.content
      .split(/\n{2,}/)
      .map((block) => block.trim())
      .filter(Boolean)
      .map((block, blockIndex) => renderMarkdownBlock(block, `segment-${segmentIndex}-block-${blockIndex}`))
  })
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
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const waitForPaint = () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()))

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
        return next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      })
    } catch (error) {
      console.error('Failed to fetch assistant history:', error)
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
    if (open) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, open, sending])

  const handleCreateSession = async () => {
    try {
      const res = await assistantApi.createSession()
      setSessions((prev) => [res.data, ...prev])
      setActiveSessionId(res.data.id)
      setMessages([])
    } catch (error) {
      console.error('Failed to create assistant session:', error)
      alert('创建会话失败')
    }
  }

  const handleDeleteSession = async () => {
    if (!sessionToDelete || deletingSession) return

    setDeletingSession(true)
    try {
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
      alert('删除会话失败')
    } finally {
      setDeletingSession(false)
    }
  }

  const handleSend = async () => {
    const message = draft.trim()
    if (!message || sending) return

    let sessionId = activeSessionId
    if (!sessionId) {
      try {
        const res = await assistantApi.createSession()
        sessionId = res.data.id
        setSessions((prev) => [res.data, ...prev])
        setActiveSessionId(res.data.id)
      } catch (error) {
        console.error('Failed to create session before sending:', error)
        alert('创建会话失败')
        return
      }
    }

    setSending(true)
    const tempUserId = Date.now()
    const tempAssistantId = tempUserId + 1
    const now = new Date().toISOString()
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: 'user', content: message, created_at: now },
      { id: tempAssistantId, role: 'assistant', content: '', created_at: now },
    ])
    setDraft('')

    try {
      const response = await assistantApi.streamChat(message, sessionId)
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentAssistantId = tempAssistantId

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
              return next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
            })
            setActiveSessionId(payload.session.id)
            setMessages((prev) => {
              const next = [...prev]
              const userIndex = next.findIndex((item) => item.id === tempUserId)
              if (userIndex >= 0) next[userIndex] = payload.user_message
              return next
            })
          }

          if (eventName === 'chunk') {
            setMessages((prev) => prev.map((item) => item.id === currentAssistantId ? { ...item, content: `${item.content}${payload.content}` } : item))
            await waitForPaint()
          }

          if (eventName === 'done' && payload.assistant_message) {
            currentAssistantId = payload.assistant_message.id
            setSessions((prev) => {
              const exists = prev.some((item) => item.id === payload.session.id)
              const next = exists ? prev.map((item) => item.id === payload.session.id ? payload.session : item) : [payload.session, ...prev]
              return next.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
            })
            setMessages((prev) => {
              const next = [...prev]
              const assistantIndex = next.findIndex((item) => item.id === tempAssistantId)
              if (assistantIndex >= 0) next[assistantIndex] = payload.assistant_message
              return next
            })
          }
        }
      }
    } catch (error) {
      console.error('Failed to send assistant message:', error)
      setMessages((prev) => prev.filter((item) => item.id !== tempUserId && item.id !== tempAssistantId))
      alert('发送消息失败，请稍后重试')
    } finally {
      setSending(false)
    }
  }

  const formatTime = (value: string) =>
    new Date(value).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })

  return (
    <>
      {open && (
        <div className={`${isMobile ? 'fixed inset-0 z-50 flex flex-col bg-white' : 'fixed bottom-24 right-6 z-50 flex h-[620px] w-[780px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/15'}`}>
          <div className={`${isMobile ? `${showMobileSessions ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col bg-slate-50` : 'flex w-[240px] flex-col border-r bg-slate-50'}`}>
            <div className="bg-gradient-to-br from-slate-900 via-slate-800 to-emerald-700 px-4 py-4 text-white">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium text-emerald-100">
                    <MemoryStick className="h-4 w-4" />
                    会话记忆
                  </div>
                  <div className="mt-1 text-lg font-semibold">智能体助手</div>
                </div>
                <Button variant="ghost" size="icon" className="h-8 w-8 text-white hover:bg-white/10 hover:text-white" onClick={() => setOpen(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <Button size="sm" className="mt-4 w-full bg-white/10 text-white hover:bg-white/20" onClick={handleCreateSession}>
                <Plus className="mr-2 h-4 w-4" />
                新建会话
              </Button>
            </div>

            <div className="flex-1 space-y-2 overflow-y-auto p-3">
              {loadingSessions && <div className="flex items-center justify-center py-8 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载会话中...</div>}
              {!loadingSessions && sessions.length === 0 && <div className="rounded-xl border border-dashed bg-white px-3 py-4 text-xs text-muted-foreground">暂无会话，点击上方新建。</div>}
              {sessions.map((session) => (
                <button
                  key={session.id}
                  onClick={() => {
                    setActiveSessionId(session.id)
                    if (isMobile) {
                      setShowMobileSessions(false)
                    }
                  }}
                  className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${activeSessionId === session.id ? 'border-emerald-300 bg-emerald-50' : 'border-transparent bg-white hover:border-slate-200 hover:bg-slate-100'}`}
                >
                  <div className="truncate text-sm font-medium text-slate-900">{session.title}</div>
                  <div className="mt-1 line-clamp-2 text-[11px] text-slate-500">{session.last_message_preview || '暂无消息'}</div>
                  <div className="mt-2 text-[10px] text-slate-400">{formatTime(session.updated_at)}</div>
                </button>
              ))}
            </div>
          </div>

          <div className={`${isMobile && showMobileSessions ? 'hidden' : 'flex'} min-h-0 flex-1 flex-col`}>
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div className="min-w-0">
                {isMobile && (
                  <button
                    className="mb-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => setShowMobileSessions(true)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5 rotate-180" />
                    会话列表
                  </button>
                )}
                <div className="text-sm font-semibold text-slate-900">
                  {sessions.find((item) => item.id === activeSessionId)?.title || '当前会话'}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">回答会参考当前持仓、账户概况和该会话上下文</div>
              </div>
              {activeSessionId && (
                <button
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    const activeSession = sessions.find((item) => item.id === activeSessionId)
                    if (activeSession) {
                      setSessionToDelete(activeSession)
                    }
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  删除会话
                </button>
              )}
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50/70 px-4 py-4">
              {loadingHistory && <div className="flex items-center justify-center py-10 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载对话中...</div>}
              {!loadingHistory && messages.length === 0 && (
                <div className="rounded-2xl border border-dashed bg-white px-4 py-5 text-sm leading-relaxed text-muted-foreground">
                  可以直接问：
                  <br />
                  “我当前仓位是否太高？”
                  <br />
                  “结合我的持仓，接下来优先减哪一类？”
                </div>
              )}
              {!loadingHistory && messages.map((message) => (
                <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[92%] md:max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm ${message.role === 'user' ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-800'}`}>
                    <div className={`space-y-3 ${message.role === 'assistant' ? 'text-[13px]' : 'whitespace-pre-wrap leading-relaxed'}`}>
                      {message.role === 'assistant' ? renderAssistantContent(message.content) : message.content}
                    </div>
                    <div className={`mt-1 text-[10px] ${message.role === 'user' ? 'text-slate-300' : 'text-slate-400'}`}>{formatTime(message.created_at)}</div>
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-muted-foreground shadow-sm">
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      助手正在思考...
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="border-t bg-white p-3 pb-[max(12px,env(safe-area-inset-bottom))]">
              <div className="rounded-2xl border bg-slate-50 p-2">
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
                  className="min-h-[84px] w-full resize-none border-0 bg-transparent p-1 text-sm outline-none placeholder:text-slate-400"
                />
                <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <span className="text-[11px] text-muted-foreground">Enter 发送，Shift+Enter 换行</span>
                  <Button size="sm" onClick={handleSend} disabled={sending || !draft.trim()}>
                    {sending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                    发送
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

import { useEffect, useRef, useState } from 'react'
import { Bot, Loader2, MemoryStick, MessageCircle, Send, Trash2, X } from 'lucide-react'

import { assistantApi, type AssistantMessage } from '@/services/api'
import { Button } from '@/components/ui/button'

function renderInline(text: string) {
  const parts = text.split(/(\*\*.*?\*\*)/g).filter(Boolean)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={`${part}-${index}`} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <span key={`${part}-${index}`}>{part}</span>
  })
}

function renderAssistantContent(content: string) {
  const blocks = content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)

  return blocks.map((block, blockIndex) => {
    const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
    const isList = lines.every((line) => /^([-*]|\d+\.)\s+/.test(line))

    if (isList) {
      return (
        <div key={`block-${blockIndex}`} className="space-y-2">
          {lines.map((line, lineIndex) => {
            const text = line.replace(/^([-*]|\d+\.)\s+/, '')
            return (
              <div key={`line-${lineIndex}`} className="flex gap-2 leading-6">
                <span className="mt-2 h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <div>{renderInline(text)}</div>
              </div>
            )
          })}
        </div>
      )
    }

    if (lines.length === 1) {
      return (
        <p key={`block-${blockIndex}`} className="leading-7">
          {renderInline(lines[0])}
        </p>
      )
    }

    return (
      <div key={`block-${blockIndex}`} className="space-y-1.5">
        {lines.map((line, lineIndex) => (
          <p key={`line-${lineIndex}`} className="leading-7">
            {renderInline(line)}
          </p>
        ))}
      </div>
    )
  })
}

export function FloatingAssistant() {
  const [open, setOpen] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [sending, setSending] = useState(false)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [draft, setDraft] = useState('')
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const waitForPaint = () =>
    new Promise<void>((resolve) => {
      window.requestAnimationFrame(() => resolve())
    })

  const fetchHistory = async () => {
    setLoadingHistory(true)
    try {
      const res = await assistantApi.getHistory()
      setMessages(res.data.messages || [])
    } catch (error) {
      console.error('Failed to fetch assistant history:', error)
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchHistory()
    }
  }, [open])

  useEffect(() => {
    if (open) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, open, sending])

  const handleSend = async () => {
    const message = draft.trim()
    if (!message || sending) return

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
      const response = await assistantApi.streamChat(message)
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
            setMessages((prev) => {
              const next = [...prev]
              const userIndex = next.findIndex((item) => item.id === tempUserId)
              if (userIndex >= 0) next[userIndex] = payload.user_message
              return next
            })
          }

          if (eventName === 'chunk') {
            setMessages((prev) =>
              prev.map((item) =>
                item.id === currentAssistantId
                  ? { ...item, content: `${item.content}${payload.content}` }
                  : item,
                ),
            )
            await waitForPaint()
          }

          if (eventName === 'done' && payload.assistant_message) {
            currentAssistantId = payload.assistant_message.id
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

  const handleClearHistory = async () => {
    if (!confirm('确定清空智能体助手的对话记忆？')) return

    try {
      await assistantApi.clearHistory()
      setMessages([])
    } catch (error) {
      console.error('Failed to clear assistant history:', error)
      alert('清空记忆失败')
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
        <div className="fixed bottom-24 right-6 z-50 w-[360px] rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/15">
          <div className="rounded-t-2xl bg-gradient-to-br from-slate-900 via-slate-800 to-emerald-700 px-4 py-4 text-white">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-100">
                  <MemoryStick className="h-4 w-4" />
                  持仓上下文 + 对话记忆
                </div>
                <div className="mt-1 text-lg font-semibold">智能体助手</div>
                <p className="mt-1 text-xs leading-relaxed text-slate-200">
                  回答时会参考当前持仓、账户概况和最近对话。
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-white hover:bg-white/10 hover:text-white"
                onClick={() => setOpen(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="flex items-center justify-between border-b px-4 py-2 text-xs text-muted-foreground">
            <span>助手会记住最近对话上下文</span>
            <button className="flex items-center gap-1 hover:text-foreground" onClick={handleClearHistory}>
              <Trash2 className="h-3.5 w-3.5" />
              清空记忆
            </button>
          </div>

          <div className="h-[360px] space-y-3 overflow-y-auto bg-slate-50/70 px-4 py-4">
            {loadingHistory && (
              <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                加载对话中...
              </div>
            )}

            {!loadingHistory && messages.length === 0 && (
              <div className="rounded-2xl border border-dashed bg-white px-4 py-5 text-sm leading-relaxed text-muted-foreground">
                可以直接问：
                <br />
                “我当前仓位是否太高？”
                <br />
                “结合我的持仓，接下来优先减哪一类？”
              </div>
            )}

            {!loadingHistory &&
              messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                      message.role === 'user'
                        ? 'bg-slate-900 text-white'
                        : 'border border-slate-200 bg-white text-slate-800'
                    }`}
                  >
                    <div className={`space-y-3 ${message.role === 'assistant' ? 'text-[13px]' : 'whitespace-pre-wrap leading-relaxed'}`}>
                      {message.role === 'assistant' ? renderAssistantContent(message.content) : message.content}
                    </div>
                    <div
                      className={`mt-1 text-[10px] ${
                        message.role === 'user' ? 'text-slate-300' : 'text-slate-400'
                      }`}
                    >
                      {formatTime(message.created_at)}
                    </div>
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

          <div className="border-t bg-white p-3">
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
              <div className="mt-2 flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">Enter 发送，Shift+Enter 换行</span>
                <Button size="sm" onClick={handleSend} disabled={sending || !draft.trim()}>
                  {sending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                  发送
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((value) => !value)}
        className="fixed bottom-6 right-6 z-50 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-slate-900 via-slate-800 to-emerald-600 text-white shadow-2xl shadow-slate-900/25 transition-transform hover:scale-105"
        title="打开智能体助手"
      >
        {open ? <X className="h-7 w-7" /> : <MessageCircle className="h-7 w-7" />}
      </button>

      {!open && (
        <div className="fixed bottom-7 right-24 z-40 rounded-full border border-emerald-200 bg-white/95 px-3 py-1.5 text-xs text-slate-600 shadow-lg backdrop-blur">
          <span className="flex items-center gap-1.5">
            <Bot className="h-3.5 w-3.5 text-emerald-600" />
            智能体助手
          </span>
        </div>
      )}
    </>
  )
}

import { Badge } from '@/components/ui/badge'
import { type EventContext, type EventItem } from '@/services/api'

type AdviceEventContextPanelProps = {
  eventContext?: EventContext | null
  compact?: boolean
  className?: string
  title?: string
}

type Tone = 'positive' | 'neutral' | 'negative' | 'unknown'

const toneClassMap: Record<Tone, string> = {
  positive: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  neutral: 'border-blue-200 bg-blue-50 text-blue-700',
  negative: 'border-red-200 bg-red-50 text-red-700',
  unknown: 'border-gray-200 bg-gray-50 text-gray-600',
}

const statusClassMap: Record<string, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  partial: 'border-amber-200 bg-amber-50 text-amber-700',
  unavailable: 'border-gray-200 bg-gray-50 text-gray-600',
  high: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  medium: 'border-blue-200 bg-blue-50 text-blue-700',
  low: 'border-amber-200 bg-amber-50 text-amber-700',
  direct: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  indirect: 'border-blue-200 bg-blue-50 text-blue-700',
  weak: 'border-amber-200 bg-amber-50 text-amber-700',
  positive: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  negative: 'border-red-200 bg-red-50 text-red-700',
}

function statusLabel(value?: string | null) {
  if (!value) return 'unknown'
  return value
}

function renderBadge(value: string | null | undefined, labelPrefix = '') {
  const displayValue = value || 'unknown'
  return (
    <Badge variant="outline" className={`text-xs ${statusClassMap[displayValue] || toneClassMap.unknown} border-current`}>
      {labelPrefix}{statusLabel(displayValue)}
    </Badge>
  )
}

function splitEventDetail(detail: string) {
  const parts = detail.split(' - ')
  return {
    title: parts[0]?.trim() || '未命名事件',
    summary: parts.slice(1).join(' - ').trim() || '暂无摘要',
  }
}

function parseEventLine(line: string): EventItem | null {
  const match = line.match(/^\d+\.\s*(.+?)\s+\[([^\]]+)\]\s*(.*)$/)
  if (!match) return null

  const meta = match[1].trim()
  const bracketParts = match[2].split('/')
  const detail = match[3].trim()
  const tokens = meta.split(/\s+/).filter(Boolean)
  const date = tokens[0] || null
  const source = tokens.slice(1).join(' ') || '来源未知'
  const relevance = bracketParts[0]?.trim() || 'unknown'
  const impact = bracketParts[1]?.trim() || 'unknown'
  const pricedToken = bracketParts[2]?.trim() || 'priced_in=unknown'
  const priced_in_risk = pricedToken.includes('=') ? pricedToken.split('=').pop() || 'unknown' : pricedToken
  const { title, summary } = splitEventDetail(detail)

  return {
    date,
    source,
    relevance,
    impact,
    priced_in_risk,
    title,
    summary,
  }
}

export function parseEventContextFromReason(reason: string | null): EventContext | null {
  const text = reason || ''
  if (!text.includes('事件上下文：') && !text.includes('搜索状态：')) {
    return null
  }

  const section = text.split('事件上下文：')[1]
  if (!section) {
    return null
  }

  const block = section.split(/\n\n【(?:短期|中期|长期)】/)[0].trim()
  const lines = block.split('\n').map((item) => item.trim()).filter(Boolean)
  if (lines.length === 0) {
    return null
  }

  const pick = (prefix: string, fallback = 'unknown') => {
    const line = lines.find((item) => item.startsWith(prefix))
    return line ? line.replace(prefix, '').trim() || fallback : fallback
  }

  const events = lines
    .map((line) => parseEventLine(line))
    .filter((item): item is EventItem => item != null)

  return {
    search_status: pick('搜索状态：', 'unavailable'),
    source_quality: pick('来源质量：', 'unknown'),
    policy_signal: pick('政策信号：', 'unknown'),
    macro_signal: pick('宏观信号：', 'unknown'),
    news_signal: pick('新闻信号：', 'unknown'),
    events,
  }
}

export function AdviceEventContextPanel({
  eventContext,
  compact = false,
  className = '',
  title = '事件上下文',
}: AdviceEventContextPanelProps) {
  if (!eventContext) return null

  const events = (eventContext.events || []).filter(Boolean)
  const visibleEvents = compact ? events.slice(0, 3) : events

  return (
    <div className={`rounded-xl border bg-background/60 ${compact ? 'p-3' : 'p-4'} ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="text-xs font-medium text-muted-foreground">{title}</div>
        {renderBadge(eventContext.search_status, '搜索：')}
        {renderBadge(eventContext.source_quality, '来源：')}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {renderBadge(eventContext.policy_signal, '政策：')}
        {renderBadge(eventContext.macro_signal, '宏观：')}
        {renderBadge(eventContext.news_signal, '新闻：')}
      </div>

      {visibleEvents.length > 0 && (
        <div className="mt-3 space-y-2">
          {visibleEvents.map((event, index) => (
            <div key={`${event.title}-${index}`} className="rounded-lg border bg-white/70 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-foreground">
                  {event.title || '未命名事件'}
                </span>
                {event.date && (
                  <Badge variant="outline" className="border-gray-200 bg-gray-50 text-xs text-gray-600">
                    {event.date}
                  </Badge>
                )}
                {event.source && (
                  <Badge variant="outline" className="border-blue-200 bg-blue-50 text-xs text-blue-700">
                    {event.source}
                  </Badge>
                )}
              </div>

              <div className="mt-2 flex flex-wrap gap-2">
                {renderBadge(event.relevance, '相关性：')}
                {renderBadge(event.impact, '影响：')}
                {renderBadge(event.priced_in_risk, '定价：')}
              </div>

              <p className={`mt-2 text-xs leading-relaxed text-muted-foreground ${compact ? '' : 'sm:text-sm'}`}>
                {event.summary || '暂无摘要'}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

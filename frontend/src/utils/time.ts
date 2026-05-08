const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

const DEFAULT_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}

const HAS_TIMEZONE_SUFFIX = /(?:Z|[+-]\d{2}:\d{2})$/i
const LOCAL_DATE_TIME = /^\d{4}[/-]\d{2}[/-]\d{2}[ T]\d{2}:\d{2}(:\d{2}(?:\.\d+)?)?$/

function normalizeTimestamp(value: string) {
  const trimmed = value.trim()
  if (HAS_TIMEZONE_SUFFIX.test(trimmed)) {
    return trimmed.replace(' ', 'T')
  }

  if (LOCAL_DATE_TIME.test(trimmed)) {
    return `${trimmed.replace(/\//g, '-').replace(' ', 'T')}+08:00`
  }

  return trimmed
}

export function parseBeijingDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(normalizeTimestamp(value))
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatBeijingTime(
  value: string | null | undefined,
  options: Intl.DateTimeFormatOptions = {},
  emptyText = '-',
) {
  const date = parseBeijingDate(value)
  if (!date) return emptyText

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    ...DEFAULT_TIME_OPTIONS,
    ...options,
  }).format(date)
}

export function compareBeijingTimeDesc(a: string | null | undefined, b: string | null | undefined) {
  const aTime = parseBeijingDate(a)?.getTime() ?? 0
  const bTime = parseBeijingDate(b)?.getTime() ?? 0
  return bTime - aTime
}

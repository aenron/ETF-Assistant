import { useEffect, useState } from 'react'
import { adviceApi, type AdviceLogResponse } from '@/services/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RefreshCw, TrendingUp, TrendingDown, Minus, Plus, ArrowDownRight, Bot, Clock, BarChart3 } from 'lucide-react'

const adviceTypeConfig: Record<string, { label: string; color: string; bgColor: string; icon: typeof TrendingUp }> = {
  buy: { label: '买入', color: 'text-red-600', bgColor: 'bg-red-50 border-red-200', icon: TrendingUp },
  sell: { label: '卖出', color: 'text-green-600', bgColor: 'bg-green-50 border-green-200', icon: TrendingDown },
  hold: { label: '持有', color: 'text-blue-600', bgColor: 'bg-blue-50 border-blue-200', icon: Minus },
  add: { label: '加仓', color: 'text-orange-600', bgColor: 'bg-orange-50 border-orange-200', icon: Plus },
  reduce: { label: '减仓', color: 'text-yellow-600', bgColor: 'bg-yellow-50 border-yellow-200', icon: ArrowDownRight },
}

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 80 ? 'bg-green-500' : value >= 60 ? 'bg-blue-500' : value >= 40 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs text-muted-foreground font-mono">{value?.toFixed(0)}%</span>
    </div>
  )
}

export function AdvicePage() {
  const [logs, setLogs] = useState<AdviceLogResponse[]>([])
  const [loading, setLoading] = useState(true)

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const res = await adviceApi.getHistory(100)
      setLogs(res.data)
    } catch (error) {
      console.error('Failed to fetch logs:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">决策历史</h1>
        <Button variant="outline" size="icon" onClick={fetchLogs} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <div className="space-y-4">
        {logs.map((log) => {
          const config = adviceTypeConfig[log.advice_type || 'hold'] || adviceTypeConfig.hold
          const Icon = config.icon
          return (
            <Card key={log.id} className={`border ${config.bgColor} transition-shadow hover:shadow-md`}>
              <CardContent className="py-4 space-y-3">
                {/* 头部: 代码 + 建议类型 + 置信度 + 时间 */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-lg font-semibold">{log.etf_code || '-'}</span>
                    <Badge variant="outline" className={`${config.color} border-current font-medium`}>
                      <Icon className="h-3 w-3 mr-1" />
                      {config.label}
                    </Badge>
                    <div className="flex items-center gap-1">
                      <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
                      <ConfidenceBar value={log.confidence || 0} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-muted-foreground text-xs">
                    <Clock className="h-3 w-3" />
                    {new Date(log.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
                  </div>
                </div>

                {/* 分析理由 */}
                <p className="text-sm leading-relaxed text-foreground/80">{log.reason || '-'}</p>

                {/* 底部: 模型信息 */}
                {(log.llm_provider || log.llm_model) && (
                  <div className="flex items-center gap-1.5 pt-1 border-t border-border/50">
                    <Bot className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">
                      {log.llm_provider && <span className="font-medium">{log.llm_provider}</span>}
                      {log.llm_model && <span className="ml-1 opacity-75">({log.llm_model})</span>}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
        {logs.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center text-muted-foreground">
              暂无历史建议记录
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

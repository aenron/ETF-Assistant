import { useEffect, useState } from 'react'
import { adviceApi, type AdviceLogResponse } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { RefreshCw, TrendingUp, TrendingDown, Minus, Plus, ArrowDownRight } from 'lucide-react'

const adviceTypeConfig: Record<string, { label: string; color: string; icon: typeof TrendingUp }> = {
  buy: { label: '买入', color: 'text-red-500', icon: TrendingUp },
  sell: { label: '卖出', color: 'text-green-500', icon: TrendingDown },
  hold: { label: '持有', color: 'text-gray-500', icon: Minus },
  add: { label: '加仓', color: 'text-orange-500', icon: Plus },
  reduce: { label: '减仓', color: 'text-yellow-600', icon: ArrowDownRight },
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
            <Card key={log.id}>
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-lg">{log.etf_code || '-'}</span>
                    <span className={`flex items-center gap-1 ${config.color}`}>
                      <Icon className="h-4 w-4" />
                      {config.label}
                    </span>
                    <span className="text-muted-foreground text-sm">
                      置信度: {log.confidence?.toFixed(0) || 0}%
                    </span>
                  </div>
                  <span className="text-muted-foreground text-sm">
                    {new Date(log.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
                  </span>
                </div>
                <p className="mt-2 text-sm">{log.reason || '-'}</p>
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

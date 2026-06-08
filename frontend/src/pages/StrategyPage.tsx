import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, Loader2, Play, RefreshCw, ShieldCheck } from 'lucide-react'

import { strategyApi, type StrategyRunResponse, type StrategyScheduleResponse, type StrategySignalResult } from '@/services/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { formatBeijingTime } from '@/utils/time'

const signalTone: Record<StrategySignalResult['signal'], string> = {
  entry: 'border-red-300 bg-red-50 text-red-700',
  hold: 'border-blue-300 bg-blue-50 text-blue-700',
  reduce: 'border-amber-300 bg-amber-50 text-amber-700',
  exit: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  avoid: 'border-slate-300 bg-slate-50 text-slate-700',
  insufficient_data: 'border-zinc-300 bg-zinc-50 text-zinc-600',
}

function formatNumber(value: number | null, digits = 3) {
  return value == null || !Number.isFinite(value) ? '-' : value.toFixed(digits)
}

function formatPct(value: number | null, digits = 2) {
  return value == null || !Number.isFinite(value) ? '-' : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

function formatVolume(value: number | null) {
  if (value == null || !Number.isFinite(value)) return '-'
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`
  if (value >= 10000) return `${(value / 10000).toFixed(0)}万`
  return value.toFixed(0)
}

function getDecisionText(item: StrategySignalResult) {
  const actionMap: Record<StrategySignalResult['signal'], string> = {
    entry: '可分批入场或加仓',
    hold: item.grid_action ? '可按网格持有运行' : '继续持有，暂不调仓',
    reduce: '建议减仓，控制追高风险',
    exit: '建议离场或调仓',
    avoid: '暂不操作，继续观察',
    insufficient_data: '暂不决策，等待更多数据',
  }
  const reason = item.reasons[0] || item.risk_flags[0] || '暂无明确触发条件'
  return `${actionMap[item.signal]}：${reason}`
}

export function StrategyPage() {
  const [latestRun, setLatestRun] = useState<StrategyRunResponse | null>(null)
  const [schedule, setSchedule] = useState<StrategyScheduleResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [scheduleBusy, setScheduleBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error' | 'neutral'>('neutral')

  const loadData = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const [latestRes, scheduleRes] = await Promise.all([
        strategyApi.getLatest(),
        strategyApi.getSchedule(),
      ])
      setLatestRun(latestRes.data)
      setSchedule(scheduleRes.data)
    } catch (error: any) {
      console.error('Failed to load strategy data:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '加载策略数据失败')
    } finally {
      setLoading(false)
    }
  }

  const runStrategy = async () => {
    setRunning(true)
    setMessage(null)
    try {
      const res = await strategyApi.run('tfss_v1')
      setLatestRun(res.data)
      setMessageTone('success')
      setMessage(`策略运行完成，分析 ${res.data.total} 个场内 ETF 持仓`)
    } catch (error: any) {
      console.error('Failed to run strategy:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '策略运行失败')
    } finally {
      setRunning(false)
    }
  }

  const updateSchedule = async (enabled: boolean) => {
    setScheduleBusy(true)
    setMessage(null)
    try {
      const res = await strategyApi.setSchedule(enabled)
      setSchedule(res.data)
      setMessageTone('success')
      setMessage(enabled ? '定时运行已开启' : '定时运行已关闭')
    } catch (error: any) {
      console.error('Failed to update strategy schedule:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '更新定时运行失败')
    } finally {
      setScheduleBusy(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const stats = useMemo(() => {
    const results = latestRun?.results || []
    return {
      total: results.length,
      entry: results.filter((item) => item.signal === 'entry').length,
      hold: results.filter((item) => item.signal === 'hold').length,
      risk: results.filter((item) => item.signal === 'reduce' || item.signal === 'exit').length,
    }
  }, [latestRun])

  const bannerClassName =
    messageTone === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : messageTone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-slate-200 bg-slate-50 text-slate-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">交易策略</h1>
          <p className="mt-1 text-sm text-muted-foreground">后端执行规则化策略，遍历当前持仓中的场内 ETF 并生成交易信号。</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" onClick={loadData} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          <Button onClick={runStrategy} disabled={running}>
            {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
            手动运行
          </Button>
        </div>
      </div>

      {message && <div className={`rounded-xl border px-4 py-3 text-sm ${bannerClassName}`}>{message}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-5 w-5 text-primary" />
              ETF 决策引擎
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm leading-relaxed text-muted-foreground">
              ETF 决策引擎先用 20 日动能扫描观察池，再用趋势跟随内核判断主升浪、震荡带或弱势；主升浪运行均线回踩与乖离率保护，震荡带运行趋势过滤网格，最后用 MA10 与 MACD 死叉做强制风控。
            </p>
            <div className="grid gap-3 sm:grid-cols-4">
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">分析标的</div>
                <div className="mt-1 text-xl font-semibold">{stats.total}</div>
              </div>
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">入场/加仓</div>
                <div className="mt-1 text-xl font-semibold text-red-600">{stats.entry}</div>
              </div>
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">持有</div>
                <div className="mt-1 text-xl font-semibold text-blue-600">{stats.hold}</div>
              </div>
              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground">减仓/离场</div>
                <div className="mt-1 text-xl font-semibold text-emerald-600">{stats.risk}</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-5 w-5 text-primary" />
              定时运行
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">浏览器外后台执行</div>
                <div className="text-xs text-muted-foreground">{schedule?.enabled ? '已开启' : '未开启'}</div>
              </div>
              <Switch checked={!!schedule?.enabled} disabled={scheduleBusy} onCheckedChange={updateSchedule} />
            </div>
            <div className="rounded-lg border bg-muted/30 p-3 text-sm">
              <div className="font-medium">运行时间</div>
              <div className="mt-1 text-muted-foreground">{schedule?.cron || '交易日 14:40'}</div>
            </div>
            {schedule?.next_run_time && (
              <div className="text-xs text-muted-foreground">
                下次运行：{formatBeijingTime(schedule.next_run_time)}
              </div>
            )}
            <p className="text-xs leading-relaxed text-muted-foreground">
              定时任务运行后会通过已启用的通知接口推送策略信号摘要。
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center justify-between gap-3 text-base">
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-primary" />
              策略信号
            </span>
            <span className="text-xs font-normal text-muted-foreground">
              最近运行：{formatBeijingTime(latestRun?.run_at || null, {}, '尚未运行')}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex h-40 items-center justify-center text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              加载中...
            </div>
          ) : latestRun?.results.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1360px] text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="px-2 py-2 text-left">ETF</th>
                    <th className="px-2 py-2 text-left">信号</th>
                    <th className="px-2 py-2 text-left">决策</th>
                    <th className="px-2 py-2 text-left">阶段</th>
                    <th className="px-2 py-2 text-right">动能</th>
                    <th className="px-2 py-2 text-right">置信度</th>
                    <th className="px-2 py-2 text-right">MA5/10/20</th>
                    <th className="px-2 py-2 text-right">MACD</th>
                    <th className="px-2 py-2 text-right">RSI</th>
                    <th className="px-2 py-2 text-right">成交量</th>
                    <th className="px-2 py-2 text-right">ATR止损</th>
                    <th className="px-2 py-2 text-left">依据</th>
                  </tr>
                </thead>
                <tbody>
                  {latestRun.results.map((item) => (
                    <tr key={item.etf_code} className="border-b align-top hover:bg-muted/30">
                      <td className="px-2 py-3">
                        <div className="font-mono font-semibold">{item.etf_code}</div>
                        <div className="max-w-40 truncate text-xs text-muted-foreground">{item.etf_name || '-'}</div>
                      </td>
                      <td className="px-2 py-3">
                        <Badge variant="outline" className={signalTone[item.signal]}>
                          {item.signal_label}
                        </Badge>
                      </td>
                      <td className="px-2 py-3">
                        <div className="max-w-72 text-xs leading-relaxed">
                          <div className="font-medium text-foreground">{getDecisionText(item)}</div>
                          {item.protection_action && <div className="mt-1 text-amber-700">{item.protection_action}</div>}
                          {item.grid_action && <div className="mt-1 text-blue-700">{item.grid_action}</div>}
                        </div>
                      </td>
                      <td className="px-2 py-3 text-xs">
                        <div className="font-medium">{item.engine_phase || '-'}</div>
                        {item.rotation_top && <div className="text-red-600">动能目标</div>}
                      </td>
                      <td className="px-2 py-3 text-right font-mono text-xs">
                        {formatPct(item.momentum20)}
                        <div className="text-muted-foreground">#{item.rotation_rank || '-'}</div>
                      </td>
                      <td className="px-2 py-3 text-right font-mono">{item.confidence}%</td>
                      <td className="px-2 py-3 text-right font-mono text-xs">
                        {formatNumber(item.ma5)} / {formatNumber(item.ma10)} / {formatNumber(item.ma20)}
                      </td>
                      <td className="px-2 py-3 text-right font-mono text-xs">
                        {formatNumber(item.macd_dif, 4)} / {formatNumber(item.macd_dea, 4)}
                      </td>
                      <td className="px-2 py-3 text-right font-mono">{formatNumber(item.rsi14, 2)}</td>
                      <td className="px-2 py-3 text-right font-mono text-xs">
                        {formatVolume(item.volume)} / {formatVolume(item.volume_ma10)}
                      </td>
                      <td className="px-2 py-3 text-right font-mono text-xs">
                        {formatNumber(item.atr_stop_price)}
                        <div className="text-muted-foreground">ATR {formatNumber(item.atr14)}</div>
                      </td>
                      <td className="px-2 py-3">
                        <div className="max-w-sm space-y-1 text-xs leading-relaxed">
                          {item.grid_action && <div className="text-blue-700">{item.grid_action}</div>}
                          {item.protection_action && <div className="text-amber-700">{item.protection_action}</div>}
                          {item.reasons.slice(0, 2).map((reason, index) => <div key={`${item.etf_code}-r-${index}`}>{reason}</div>)}
                          {item.risk_flags.map((risk, index) => (
                            <div key={`${item.etf_code}-risk-${index}`} className="flex items-center gap-1 text-amber-700">
                              <AlertTriangle className="h-3.5 w-3.5" />
                              {risk}
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              暂无策略运行结果，点击“手动运行”开始分析。
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

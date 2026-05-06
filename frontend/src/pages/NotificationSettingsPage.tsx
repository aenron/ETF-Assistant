import { useEffect, useState } from 'react'
import { Bell, CheckCircle2, Loader2, Save, Send, ShieldAlert, SendHorizonal } from 'lucide-react'

import {
  notificationConfigApi,
  type NotificationConfigResponse,
} from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

function formatTime(value: string | null) {
  if (!value) return '暂无'
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

type ProviderMessageTone = 'success' | 'error' | 'neutral'

function NotificationProviderCard({
  providerName,
  providerLabel,
  description,
  accentClassName,
  config,
  enabled,
  onEnabledChange,
  loading,
  saving,
  testing,
  message,
  messageTone,
  fields,
  onSave,
  onTest,
}: {
  providerName: string
  providerLabel: string
  description: string
  accentClassName: string
  config: NotificationConfigResponse | null
  enabled: boolean
  onEnabledChange: (value: boolean) => void
  loading: boolean
  saving: boolean
  testing: boolean
  message: string | null
  messageTone: ProviderMessageTone
  fields: React.ReactNode
  onSave: () => void
  onTest: () => void
}) {
  const bannerClassName =
    messageTone === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : messageTone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-slate-200 bg-slate-50 text-slate-700'

  return (
    <Card className="overflow-hidden border-slate-200 shadow-sm">
      <div className={`h-2 ${accentClassName}`} />
      <CardHeader className="gap-4 pb-4">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-sm font-medium text-emerald-700">
              {providerName === 'telegram' ? <SendHorizonal className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
              {providerLabel}
            </div>
            <CardTitle className="text-xl">用户级通知配置</CardTitle>
            <p className="text-sm leading-6 text-muted-foreground">{description}</p>
          </div>
          <div className={`rounded-full border px-3 py-1 text-xs font-medium ${
            config?.enabled
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : 'border-slate-200 bg-slate-50 text-slate-600'
          }`}>
            {config?.enabled ? '已启用' : '未启用'}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {message && (
          <div className={`rounded-xl border px-4 py-3 text-sm ${bannerClassName}`}>
            {message}
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border bg-slate-50/70 p-4">
            <div className="text-xs font-medium text-muted-foreground">当前状态</div>
            <div className="mt-2 flex items-center gap-2 text-sm">
              {config?.configured ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  <span>已配置必要字段</span>
                </>
              ) : (
                <>
                  <ShieldAlert className="h-4 w-4 text-amber-600" />
                  <span>未配置完整</span>
                </>
              )}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              当前保存的凭证：{config?.device_key_masked || '暂无'}
            </p>
            {config?.provider === 'telegram' && (
              <p className="mt-2 text-xs text-muted-foreground">
                当前 Chat ID：{config?.chat_id_masked || '暂无'}
              </p>
            )}
          </div>
          <div className="rounded-xl border bg-slate-50/70 p-4">
            <div className="text-xs font-medium text-muted-foreground">最近测试</div>
            <p className="mt-2 text-sm">{formatTime(config?.last_test_at || null)}</p>
            <p className={`mt-2 text-xs ${
              config?.last_test_success === true
                ? 'text-emerald-700'
                : config?.last_test_success === false
                  ? 'text-red-700'
                  : 'text-muted-foreground'
            }`}>
              {config?.last_test_success === true
                ? '最近一次测试成功'
                : config?.last_test_success === false
                  ? '最近一次测试失败'
                  : '暂无测试记录'}
            </p>
          </div>
          <div className="rounded-xl border bg-slate-50/70 p-4">
            <div className="text-xs font-medium text-muted-foreground">最近错误</div>
            <p className="mt-2 text-sm leading-6 text-foreground/80">{config?.last_error || '暂无'}</p>
          </div>
        </div>

        <div className="space-y-5">
          <div className="flex items-start justify-between gap-4 rounded-xl border p-4">
            <div>
              <div className="text-sm font-medium">启用 {providerLabel} 通知</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                开启后，系统会在后台定时分析完成时把当前用户自己的通知推送到你配置的 {providerLabel} 目标。
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`text-sm font-medium ${enabled ? 'text-emerald-700' : 'text-muted-foreground'}`}>
                {enabled ? '已开启' : '已关闭'}
              </span>
              <Switch checked={enabled} onCheckedChange={onEnabledChange} />
            </div>
          </div>

          {fields}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <Button onClick={onSave} disabled={loading || saving} className="sm:min-w-36">
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            {saving ? '保存中...' : '保存配置'}
          </Button>
          <Button variant="outline" onClick={onTest} disabled={loading || testing} className="sm:min-w-36">
            {testing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
            {testing ? '发送中...' : '发送测试通知'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function NotificationSettingsPage() {
  const [barkConfig, setBarkConfig] = useState<NotificationConfigResponse | null>(null)
  const [telegramConfig, setTelegramConfig] = useState<NotificationConfigResponse | null>(null)
  const [barkEnabled, setBarkEnabled] = useState(false)
  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [barkDeviceKey, setBarkDeviceKey] = useState('')
  const [telegramBotToken, setTelegramBotToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')
  const [barkBaseUrl, setBarkBaseUrl] = useState('https://api.day.app')
  const [telegramBaseUrl, setTelegramBaseUrl] = useState('https://api.telegram.org')
  const [loading, setLoading] = useState(true)
  const [savingBark, setSavingBark] = useState(false)
  const [savingTelegram, setSavingTelegram] = useState(false)
  const [testingBark, setTestingBark] = useState(false)
  const [testingTelegram, setTestingTelegram] = useState(false)
  const [barkMessage, setBarkMessage] = useState<string | null>(null)
  const [telegramMessage, setTelegramMessage] = useState<string | null>(null)
  const [barkMessageTone, setBarkMessageTone] = useState<ProviderMessageTone>('neutral')
  const [telegramMessageTone, setTelegramMessageTone] = useState<ProviderMessageTone>('neutral')

  const loadConfig = async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true)
    }
    try {
      const res = await notificationConfigApi.list()
      const nextBarkConfig = res.data.configs.find((item) => item.provider === 'bark') || null
      const nextTelegramConfig = res.data.configs.find((item) => item.provider === 'telegram') || null
      setBarkConfig(nextBarkConfig)
      setTelegramConfig(nextTelegramConfig)
      setBarkEnabled(Boolean(nextBarkConfig?.enabled))
      setTelegramEnabled(Boolean(nextTelegramConfig?.enabled))
      setBarkDeviceKey('')
      setTelegramBotToken('')
      setTelegramChatId('')
      setBarkBaseUrl(nextBarkConfig?.base_url || 'https://api.day.app')
      setTelegramBaseUrl(nextTelegramConfig?.base_url || 'https://api.telegram.org')
    } catch (error) {
      console.error('Failed to load notification config:', error)
      setBarkMessageTone('error')
      setTelegramMessageTone('error')
      setBarkMessage('加载通知配置失败，请刷新页面后重试。')
      setTelegramMessage('加载通知配置失败，请刷新页面后重试。')
    } finally {
      if (!options?.silent) {
        setLoading(false)
      }
    }
  }

  const handleSaveBark = async () => {
    setSavingBark(true)
    setBarkMessage(null)
    try {
      const res = await notificationConfigApi.updateBark({
        enabled: barkEnabled,
        device_key: barkDeviceKey,
        base_url: barkBaseUrl.trim() || 'https://api.day.app',
      })
      await loadConfig({ silent: true })
      if (barkEnabled && !res.data.enabled) {
        setBarkMessageTone('error')
        setBarkMessage('保存成功，但由于未填写有效的 Bark Key，通知未启用。')
      } else {
        setBarkMessageTone(res.data.enabled ? 'success' : 'neutral')
        setBarkMessage(res.data.enabled ? 'Bark 配置已保存并启用，页面状态已同步刷新。' : 'Bark 配置已保存，当前仍处于关闭状态。')
      }
    } catch (error: any) {
      console.error('Failed to save bark config:', error)
      setBarkMessageTone('error')
      setBarkMessage(error.response?.data?.detail || '保存 Bark 配置失败，请检查 Bark Key 或服务地址后重试。')
    } finally {
      setSavingBark(false)
    }
  }

  const handleTestBark = async () => {
    setTestingBark(true)
    setBarkMessage(null)
    try {
      const res = await notificationConfigApi.testBark()
      await loadConfig({ silent: true })
      setBarkMessageTone(res.data.success ? 'success' : 'error')
      setBarkMessage(res.data.message)
    } catch (error: any) {
      console.error('Failed to send bark test notification:', error)
      setBarkMessageTone('error')
      setBarkMessage(error.response?.data?.detail || '测试通知发送失败，请先确认已保存 Bark Key，并检查 Bark 服务地址是否可访问。')
    } finally {
      setTestingBark(false)
    }
  }

  const handleSaveTelegram = async () => {
    setSavingTelegram(true)
    setTelegramMessage(null)
    try {
      const res = await notificationConfigApi.updateTelegram({
        enabled: telegramEnabled,
        bot_token: telegramBotToken,
        chat_id: telegramChatId,
        base_url: telegramBaseUrl.trim() || 'https://api.telegram.org',
      })
      await loadConfig({ silent: true })
      if (telegramEnabled && !res.data.enabled) {
        setTelegramMessageTone('error')
        setTelegramMessage('保存成功，但由于未填写有效的 Bot Token 或 Chat ID，Telegram 通知未启用。')
      } else {
        setTelegramMessageTone(res.data.enabled ? 'success' : 'neutral')
        setTelegramMessage(res.data.enabled ? 'Telegram 配置已保存并启用，页面状态已同步刷新。' : 'Telegram 配置已保存，当前仍处于关闭状态。')
      }
    } catch (error: any) {
      console.error('Failed to save telegram config:', error)
      setTelegramMessageTone('error')
      setTelegramMessage(error.response?.data?.detail || '保存 Telegram 配置失败，请检查 Bot Token、Chat ID 或服务地址后重试。')
    } finally {
      setSavingTelegram(false)
    }
  }

  const handleTestTelegram = async () => {
    setTestingTelegram(true)
    setTelegramMessage(null)
    try {
      const res = await notificationConfigApi.testTelegram()
      await loadConfig({ silent: true })
      setTelegramMessageTone(res.data.success ? 'success' : 'error')
      setTelegramMessage(res.data.message)
    } catch (error: any) {
      console.error('Failed to send telegram test notification:', error)
      setTelegramMessageTone('error')
      setTelegramMessage(error.response?.data?.detail || '测试 Telegram 通知失败，请先确认已保存 Bot Token、Chat ID，并检查 Telegram API 地址是否可访问。')
    } finally {
      setTestingTelegram(false)
    }
  }

  useEffect(() => {
    loadConfig()
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">通知设置</h1>
        <p className="text-sm text-muted-foreground">
          为当前账户单独配置推送渠道。当前已支持 Bark 和 Telegram Bot，定时任务只会通知已启用配置的用户。
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <NotificationProviderCard
          providerName="bark"
          providerLabel="Bark 推送"
          description="这里的配置只作用于当前登录用户。后台收盘分析和本周分析只会发到你自己配置的 Bark 设备。"
          accentClassName="bg-gradient-to-r from-emerald-400 via-sky-400 to-blue-500"
          config={barkConfig}
          enabled={barkEnabled}
          onEnabledChange={setBarkEnabled}
          loading={loading}
          saving={savingBark}
          testing={testingBark}
          message={barkMessage}
          messageTone={barkMessageTone}
          onSave={handleSaveBark}
          onTest={handleTestBark}
          fields={
            <div className="grid gap-5 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="bark-device-key">Bark Device Key</Label>
                <Input
                  id="bark-device-key"
                  value={barkDeviceKey}
                  onChange={(event) => setBarkDeviceKey(event.target.value)}
                  placeholder={barkConfig?.configured ? '留空表示不修改当前 Key' : '请输入 Bark Device Key'}
                />
                <p className="text-xs leading-5 text-muted-foreground">
                  为安全起见，页面不会回显完整 Key。已有配置时，留空表示保持不变。
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="bark-base-url">Bark Base URL</Label>
                <Input
                  id="bark-base-url"
                  value={barkBaseUrl}
                  onChange={(event) => setBarkBaseUrl(event.target.value)}
                  placeholder="https://api.day.app"
                />
                <p className="text-xs leading-5 text-muted-foreground">
                  默认使用官方 Bark 服务；如果你自建了服务，可在这里填写自定义地址。
                </p>
              </div>
            </div>
          }
        />

        <NotificationProviderCard
          providerName="telegram"
          providerLabel="Telegram Bot"
          description="配置 Bot Token 和 Chat ID 后，后台定时分析会直接发送到你的 Telegram 对话或频道。"
          accentClassName="bg-gradient-to-r from-sky-400 via-cyan-400 to-blue-600"
          config={telegramConfig}
          enabled={telegramEnabled}
          onEnabledChange={setTelegramEnabled}
          loading={loading}
          saving={savingTelegram}
          testing={testingTelegram}
          message={telegramMessage}
          messageTone={telegramMessageTone}
          onSave={handleSaveTelegram}
          onTest={handleTestTelegram}
          fields={
            <div className="space-y-5">
              <div className="rounded-xl border border-sky-200 bg-sky-50/80 p-4">
                <div className="text-sm font-medium text-sky-900">如何获取 Telegram Chat ID</div>
                <div className="mt-2 space-y-2 text-xs leading-6 text-sky-900/80">
                  <p>1. 先用 `@BotFather` 创建机器人，拿到 Bot Token。</p>
                  <p>2. 把你的 Bot 拉进目标私聊、群组或频道，并至少发送一条消息。</p>
                  <p>3. 在浏览器打开：`https://api.telegram.org/bot&lt;你的BotToken&gt;/getUpdates`</p>
                  <p>4. 在返回结果里查找 `chat` 对象中的 `id` 字段，这个值就是 Chat ID。</p>
                  <p>5. 私聊通常是正整数，群组/频道通常是负数，直接完整填写即可。</p>
                </div>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="telegram-bot-token">Telegram Bot Token</Label>
                  <Input
                    id="telegram-bot-token"
                    value={telegramBotToken}
                    onChange={(event) => setTelegramBotToken(event.target.value)}
                    placeholder={telegramConfig?.configured ? '留空表示不修改当前 Token' : '请输入 Bot Token'}
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    可通过 `@BotFather` 创建机器人并获取 Token。已有配置时，留空表示保持不变。
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="telegram-chat-id">Telegram Chat ID</Label>
                  <Input
                    id="telegram-chat-id"
                    value={telegramChatId}
                    onChange={(event) => setTelegramChatId(event.target.value)}
                    placeholder={telegramConfig?.chat_id_masked ? '留空表示不修改当前 Chat ID' : '请输入 Chat ID'}
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    私聊、群组或频道都可以，需确保 Bot 已有发送权限，并且这个 Chat ID 来自 `getUpdates` 返回结果。
                  </p>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="telegram-base-url">Telegram API Base URL</Label>
                  <Input
                    id="telegram-base-url"
                    value={telegramBaseUrl}
                    onChange={(event) => setTelegramBaseUrl(event.target.value)}
                    placeholder="https://api.telegram.org"
                  />
                  <p className="text-xs leading-5 text-muted-foreground">
                    默认使用官方 Telegram API；如你有代理或网关，也可以在这里填写自定义地址。
                  </p>
                </div>
              </div>
            </div>
          }
        />
      </div>

      <div className="flex justify-end">
        <Button variant="ghost" onClick={() => loadConfig()} disabled={loading}>
          {loading ? '加载中...' : '重新加载全部配置'}
        </Button>
      </div>
    </div>
  )
}

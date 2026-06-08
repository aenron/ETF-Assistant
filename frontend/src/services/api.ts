import axios from 'axios'
import { getToken } from './authApi'

const api = axios.create({
  baseURL: '/api',
  timeout: 600000,  // 10分钟超时（支持LLM搜索生成）
})

// 请求拦截器 - 添加Token
api.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 - 处理401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('etf_token')
      localStorage.removeItem('etf_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// 类型定义
export interface PortfolioCreate {
  etf_code: string
  shares: number
  cost_price: number
  buy_date?: string
  note?: string
  dca_track_override?: string
}

export interface PortfolioUpdate {
  shares?: number
  cost_price?: number
  buy_date?: string
  note?: string
  dca_track_override?: string
}

export interface PortfolioWithMarket {
  id: number
  etf_code: string
  shares: number
  cost_price: number
  buy_date: string | null
  note: string | null
  dca_track_override: string | null
  created_at: string
  updated_at: string
  etf_name: string | null
  current_price: number | null
  change_pct: number | null
  market_refreshed_at: string | null
  market_value: number | null
  pnl: number | null
  pnl_pct: number | null
  today_pnl: number | null
  today_pnl_pct: number | null
  holding_days: number | null
  dca_track: string | null
  dca_light: string | null
  dca_label: string | null
  dca_action: string | null
  dca_reason: string | null
  dca_next_trigger_price: number | null
  dca_valuation_percentile: number | null
  dca_valuation_pe: number | null
  dca_valuation_pb: number | null
  dca_valuation_pe_percentile: number | null
  dca_valuation_pb_percentile: number | null
  dca_valuation_sample_size: number | null
  dca_trend_ma20: number | null
  dca_trend_ma20_slope_pct: number | null
  dca_trend_distance_pct: number | null
  dca_trend_atr14: number | null
  dca_trend_atr_band_pct: number | null
  dca_decision_steps: string[] | null
  dca_candidate_light: string | null
  dca_candidate_confirm_count: number | null
  dca_quality_score: number | null
  dca_green_trigger_price: number | null
  dca_deep_green_trigger_price: number | null
  dca_budget_multiplier: number | null
  dca_budget_label: string | null
}


export interface PortfolioDcaSignalHistoryItem {
  id: number
  portfolio_id: number
  etf_code: string
  signal_light: string | null
  persisted_light: string | null
  candidate_light: string | null
  candidate_confirm_count: number | null
  label: string | null
  action: string | null
  reason: string | null
  budget_multiplier: number | null
  trigger_price: number | null
  price: number | null
  metrics: Record<string, any> | null
  scanned_at: string
}

export interface PortfolioSummary {
  total_market_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  today_pnl: number | null
  today_pnl_pct: number | null
  category_distribution: Record<string, number>
}

export interface MarketQuote {
  code: string
  name: string
  price: number
  change_pct: number
  open_price: number | null
  high_price: number | null
  low_price: number | null
  volume: number | null
  refreshed_at: string | null
}

export interface KLineItem {
  trade_date: string
  open_price: number
  close_price: number
  high_price: number
  low_price: number
  volume: number
  change_pct: number
}

export interface TechnicalIndicators {
  ma5: number | null
  ma10: number | null
  ma20: number | null
  rsi14: number | null
  macd_dif: number | null
  macd_dea: number | null
  macd_histogram: number | null
}

export interface MarketHistoryResponse {
  code: string
  name: string
  data: KLineItem[]
  indicators: TechnicalIndicators | null
}

export interface EtfProfileResponse {
  code: string
  year: string
  basic: Record<string, unknown>
  asset_allocation: Array<Record<string, unknown>>
  stock_holdings: Array<Record<string, unknown>>
  bond_holdings: Array<Record<string, unknown>>
  events: Array<Record<string, unknown>>
  errors: string[]
  source?: string | null
  refreshed_at?: string | null
}

export interface AdviceResponse {
  etf_code: string
  etf_name: string | null
  advice_type: string
  main_judgment: string
  summary: string
  action: string
  why: string[]
  news_basis: string[]
  policy_basis: string[]
  event_context: EventContext
  reason: string
  confidence: number
  short_term: PeriodAdvice
  medium_term: PeriodAdvice
  long_term: PeriodAdvice
  current_price: number | null
  pnl_pct: number | null
  created_at: string
}

export interface PeriodAdvice {
  advice_type: string
  action: string
  conclusion: string
  signals: string[]
  risks: string[]
  confidence: number
}

export interface EventItem {
  title: string
  date: string | null
  source: string
  relevance: string
  impact: string
  priced_in_risk: string
  summary: string
}

export interface EventContext {
  search_status: string
  source_quality: string
  policy_signal: string
  macro_signal: string
  news_signal: string
  events: EventItem[]
}

export interface AccountAnalysisResponse {
  summary: string
  position_advice: string
  rebalance_advice: string
  risk_level: string
  key_actions: string[]
  confidence: number
  created_at: string
}

export interface AdviceLogResponse {
  id: number
  etf_code: string | null
  etf_name: string | null
  advice_type: string | null
  reason: string | null
  confidence: number | null
  llm_provider: string | null
  llm_model: string | null
  created_at: string
}

export interface EtfSearchResult {
  code: string
  name: string
  category: string | null
  exchange: string | null
}

export interface LLMProvider {
  id: string
  name: string
  description: string
  enabled: boolean
  supports_search: boolean
}

export interface LLMConfigResponse {
  current_provider: string
  providers: LLMProvider[]
}

export interface AssistantMessage {
  id: number
  role: string
  content: string
  created_at: string
}

export interface AssistantSession {
  id: number
  title: string
  last_message_preview: string | null
  created_at: string
  updated_at: string
}

export interface AssistantHistoryResponse {
  session: AssistantSession
  messages: AssistantMessage[]
}

export interface AssistantChatResponse {
  session: AssistantSession
  user_message: AssistantMessage
  assistant_message: AssistantMessage
}

export interface AssistantSessionListResponse {
  sessions: AssistantSession[]
}

export type MultiAgentScene = 'etf' | 'account' | 'general'

export interface MultiAgentRunCreate {
  scene: MultiAgentScene
  question?: string | null
  use_portfolio_context?: boolean
  max_debate_rounds?: number
  collapse_debate_by_default?: boolean
}

export interface MultiAgentContextSummary {
  scenario: MultiAgentScene
  title: string
  question?: string | null
  bullets: string[]
  metrics: Record<string, string>
}

export interface MultiAgentRoleOpinion {
  round_index: number
  role_id: string
  role_name: string
  stance: 'bullish' | 'neutral' | 'bearish' | 'mixed'
  action?: string
  summary: string
  evidence: string[]
  risk_notes: string[]
  confidence: number
  rebuttals?: string[]
}

export interface MultiAgentDebateRound {
  round_index: number
  role_opinions: MultiAgentRoleOpinion[]
  round_summary: string
  open_disagreements: string[]
  convergence_state: 'forming' | 'contested' | 'converged' | 'max_rounds' | 'failed'
  arbiter_summary?: MultiAgentArbiterSummary | null
}

export interface MultiAgentArbiterSummary {
  round_index: number
  consensus_reached: boolean
  why_stop: string
  strong_opposition: string[]
  confidence: number
  final_recommendation: string
  recommended_action?: string
  conclusion: string
  supporting_roles: string[]
  disagreements: string[]
  risk_notes: string[]
  convergence_state: 'forming' | 'contested' | 'converged' | 'max_rounds' | 'failed'
}

export interface MultiAgentSearchMetadata {
  provider: string
  enabled: boolean
  query: string
  answer?: string | null
  result_count: number
  error?: string | null
  results: Array<Record<string, unknown>>
}

export interface MultiAgentFinalConclusion {
  recommended_action: string
  action?: string
  conclusion: string
  confidence: number
  supporting_roles: string[]
  disagreements: string[]
  risk_notes: string[]
}

export interface MultiAgentChatTranscriptEvent {
  event: string
  payload: Record<string, unknown>
}

export interface MultiAgentRunResponse {
  run_id: number
  title: string
  scene: MultiAgentScene
  question?: string | null
  use_portfolio_context?: boolean
  max_debate_rounds: number
  collapse_debate_by_default: boolean
  llm_provider: string
  created_at: string
  context_summary: MultiAgentContextSummary
  initial_role_opinions: MultiAgentRoleOpinion[]
  role_opinions: MultiAgentRoleOpinion[]
  debate_rounds: MultiAgentDebateRound[]
  search_metadata: MultiAgentSearchMetadata[]
  arbiter_summary: MultiAgentArbiterSummary | null
  final_conclusion: MultiAgentFinalConclusion
  chat_transcript: MultiAgentChatTranscriptEvent[]
  status: 'running' | 'success' | 'partial' | 'failed'
}

export interface MultiAgentRunListResponse {
  runs: MultiAgentRunResponse[]
}

export interface NotificationConfigResponse {
  id: number | null
  provider: string
  enabled: boolean
  configured: boolean
  device_key_masked: string | null
  chat_id_masked: string | null
  base_url: string
  last_test_at: string | null
  last_test_success: boolean | null
  last_error: string | null
  created_at: string | null
  updated_at: string | null
}

export interface NotificationConfigListResponse {
  configs: NotificationConfigResponse[]
}

export interface BarkNotificationConfigUpdate {
  enabled: boolean
  device_key: string
  base_url: string
}

export interface TelegramNotificationConfigUpdate {
  enabled: boolean
  bot_token: string
  chat_id: string
  base_url: string
}

export interface NotificationTestResponse {
  success: boolean
  message: string
  config: NotificationConfigResponse
}

export interface AdminUser {
  id: number
  username: string
  email: string | null
  is_active: boolean
  is_admin: boolean
  account_balance: number | null
  created_at: string
}

export interface AdminUserUpdate {
  is_active?: boolean
  is_admin?: boolean
  account_balance?: number
}

export interface SchedulerJob {
  id: string
  name: string
  trigger: string
  next_run_time: string | null
  enabled: boolean
}

export interface SchedulerJobsResponse {
  running: boolean
  jobs: SchedulerJob[]
}

export interface SchedulerActionResponse {
  success: boolean
  message: string
  job_id?: string
}

export interface StrategyInfo {
  id: 'tfss_v1'
  name: string
  description: string
  enabled: boolean
}

export interface StrategySignalResult {
  etf_code: string
  etf_name: string | null
  signal: 'entry' | 'hold' | 'reduce' | 'exit' | 'avoid' | 'insufficient_data'
  signal_label: string
  confidence: number
  close_price: number | null
  ma5: number | null
  ma10: number | null
  ma20: number | null
  ma20_slope: number | null
  volume: number | null
  volume_ma10: number | null
  atr14: number | null
  atr_stop_price: number | null
  momentum20: number | null
  rotation_rank: number | null
  rotation_top: boolean | null
  engine_phase: string | null
  grid_action: string | null
  protection_action: string | null
  macd_dif: number | null
  macd_dea: number | null
  macd_histogram: number | null
  rsi14: number | null
  bias20: number | null
  reasons: string[]
  risk_flags: string[]
}

export interface StrategyRunResponse {
  strategy_id: 'tfss_v1'
  strategy_name: string
  run_at: string
  total: number
  results: StrategySignalResult[]
}

export interface StrategyScheduleResponse {
  strategy_id: 'tfss_v1'
  enabled: boolean
  cron: string
  job_id: string
  next_run_time: string | null
}

// API 服务
export const portfolioApi = {
  getList: () => api.get<PortfolioWithMarket[]>('/portfolio'),
  getSummary: () => api.get<PortfolioSummary>('/portfolio/summary'),
  getById: (id: number) => api.get<PortfolioWithMarket>(`/portfolio/${id}`),
  getDcaHistory: (id: number, limit = 30) => api.get<PortfolioDcaSignalHistoryItem[]>(`/portfolio/${id}/dca-history`, { params: { limit } }),
  create: (data: PortfolioCreate) => api.post('/portfolio', data),
  update: (id: number, data: PortfolioUpdate) => api.put(`/portfolio/${id}`, data),
  delete: (id: number) => api.delete(`/portfolio/${id}`),
}

export const marketApi = {
  getQuote: (code: string) => api.get<MarketQuote>(`/market/quote/${code}`),
  getHistory: (code: string, days = 60) => api.get<MarketHistoryResponse>(`/market/history/${code}`, { params: { days } }),
  getEtfProfile: (code: string, year?: number, forceRefresh = false) => api.get<EtfProfileResponse>(`/market/etf/${code}/profile`, { params: { year, force_refresh: forceRefresh } }),
  searchEtf: (q: string) => api.get<EtfSearchResult[]>('/market/etf/search', { params: { q } }),
  refreshQuote: (code: string) => api.post(`/market/refresh/${code}`),
  refreshAll: () => api.post('/market/refresh-all'),
}

export const adviceApi = {
  generate: (etfCodes?: string[]) => api.post<AdviceResponse[]>('/advice/generate', { etf_codes: etfCodes }),
  analyzeAccount: () => api.post<AccountAnalysisResponse>('/advice/account-analysis'),
  getLatestAccountAnalysis: () => api.get<AccountAnalysisResponse | null>('/advice/account-analysis/latest'),
  generateForPortfolio: (portfolioId: number) => api.get<AdviceResponse>(`/advice/generate/${portfolioId}`),
  getHistory: (limit = 50) => api.get<AdviceLogResponse[]>('/advice/history', { params: { limit } }),
  getLatest: () => api.get<Record<string, AdviceLogResponse>>('/advice/latest'),
}

export const llmApi = {
  getProviders: () => api.get<LLMConfigResponse>('/llm/providers'),
  switchProvider: (provider: string) => api.post(`/llm/switch`, null, { params: { provider } }),
}

export const assistantApi = {
  listSessions: () => api.get<AssistantSessionListResponse>('/assistant/sessions'),
  createSession: (title?: string) => api.post<AssistantSession>('/assistant/sessions', { title }),
  getHistory: (sessionId?: number) => api.get<AssistantHistoryResponse>('/assistant/history', { params: { session_id: sessionId } }),
  chat: (message: string, sessionId?: number, includePortfolioContext = true) => api.post<AssistantChatResponse>('/assistant/chat', {
    message,
    session_id: sessionId,
    include_portfolio_context: includePortfolioContext,
  }),
  deleteSession: (sessionId: number) => api.delete(`/assistant/sessions/${sessionId}`),
  streamChat: async (message: string, sessionId?: number, retryMessageId?: number, includePortfolioContext = true) =>
    fetch('/api/assistant/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
      body: JSON.stringify({
        message,
        session_id: sessionId,
        retry_message_id: retryMessageId,
        include_portfolio_context: includePortfolioContext,
      }),
    }),
}

export const strategyApi = {
  list: () => api.get<StrategyInfo[]>('/strategies'),
  run: (strategyId: 'tfss_v1' = 'tfss_v1') => api.post<StrategyRunResponse>('/strategies/run', { strategy_id: strategyId }),
  getLatest: () => api.get<StrategyRunResponse | null>('/strategies/latest'),
  getSchedule: () => api.get<StrategyScheduleResponse>('/strategies/schedule'),
  setSchedule: (enabled: boolean) => api.post<StrategyScheduleResponse>('/strategies/schedule', {
    enabled,
  }),
}

export const notificationConfigApi = {
  list: () => api.get<NotificationConfigListResponse>('/notification-configs'),
  updateBark: (data: BarkNotificationConfigUpdate) => api.put<NotificationConfigResponse>('/notification-configs/bark', data),
  updateTelegram: (data: TelegramNotificationConfigUpdate) => api.put<NotificationConfigResponse>('/notification-configs/telegram', data),
  testBark: () => api.post<NotificationTestResponse>('/notification-configs/bark/test'),
  testTelegram: () => api.post<NotificationTestResponse>('/notification-configs/telegram/test'),
}

export const adminApi = {
  listUsers: () => api.get<AdminUser[]>('/admin/users'),
  updateUser: (userId: number, data: AdminUserUpdate) => api.patch<AdminUser>(`/admin/users/${userId}`, data),
}

export const schedulerApi = {
  listJobs: () => api.get<SchedulerJobsResponse>('/admin/scheduler/jobs'),
  runJob: (jobId: string) => api.post<SchedulerActionResponse>(`/admin/scheduler/jobs/${jobId}/run`),
  pauseJob: (jobId: string) => api.post<SchedulerActionResponse>(`/admin/scheduler/jobs/${jobId}/pause`),
  resumeJob: (jobId: string) => api.post<SchedulerActionResponse>(`/admin/scheduler/jobs/${jobId}/resume`),
}

export const multiAgentApi = {
  createRun: (data: MultiAgentRunCreate) => api.post<MultiAgentRunResponse>('/multi-agent/runs', data),
  streamRun: async (data: MultiAgentRunCreate) =>
    fetch('/api/multi-agent/runs/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
      body: JSON.stringify(data),
    }),
  listRuns: () => api.get<MultiAgentRunListResponse>('/multi-agent/runs'),
  getRun: (runId: number) => api.get<MultiAgentRunResponse>(`/multi-agent/runs/${runId}`),
  updateRun: (runId: number, data: { title: string }) => api.patch<MultiAgentRunResponse>(`/multi-agent/runs/${runId}`, data),
  deleteRun: (runId: number) => api.delete<{ success: boolean }>(`/multi-agent/runs/${runId}`),
}

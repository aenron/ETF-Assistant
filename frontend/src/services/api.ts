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
}

export interface PortfolioUpdate {
  shares?: number
  cost_price?: number
  buy_date?: string
  note?: string
}

export interface PortfolioWithMarket {
  id: number
  etf_code: string
  shares: number
  cost_price: number
  buy_date: string | null
  note: string | null
  created_at: string
  updated_at: string
  etf_name: string | null
  current_price: number | null
  change_pct: number | null
  market_value: number | null
  pnl: number | null
  pnl_pct: number | null
  holding_days: number | null
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

export interface AdviceResponse {
  etf_code: string
  etf_name: string | null
  advice_type: string
  reason: string
  confidence: number
  current_price: number | null
  pnl_pct: number | null
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

// API 服务
export const portfolioApi = {
  getList: () => api.get<PortfolioWithMarket[]>('/portfolio'),
  getSummary: () => api.get<PortfolioSummary>('/portfolio/summary'),
  getById: (id: number) => api.get<PortfolioWithMarket>(`/portfolio/${id}`),
  create: (data: PortfolioCreate) => api.post('/portfolio', data),
  update: (id: number, data: PortfolioUpdate) => api.put(`/portfolio/${id}`, data),
  delete: (id: number) => api.delete(`/portfolio/${id}`),
}

export const marketApi = {
  getQuote: (code: string) => api.get<MarketQuote>(`/market/quote/${code}`),
  getHistory: (code: string, days = 60) => api.get<MarketHistoryResponse>(`/market/history/${code}`, { params: { days } }),
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

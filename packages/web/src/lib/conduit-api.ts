import type {
  Run,
  RunsListResponse,
  RunsStatsResponse,
  RunsFilters,
  Worker,
  WorkersListResponse,
  FunctionsListResponse,
  FunctionDetailResponse,
  FunctionType,
  ApisListResponse,
  ApiDetailResponse,
  DashboardStats,
} from './interfaces'

class ConduitAPIClass {
  private apiUrl: string
  private static VERSION_PREFIX = '/api/v1'

  constructor() {
    this.apiUrl = process.env.CONDUIT_API_URL || 'http://localhost:8000'
  }

  // ============ Utility Methods ============

  private async fetchWithApiUrl<T>(
    endpoint: string,
    options?: RequestInit,
  ): Promise<T> {
    const headers = new Headers(options?.headers)

    if (options?.body) {
      headers.set('Content-Type', 'application/json')
    }

    const response = await fetch(
      `${this.apiUrl}${ConduitAPIClass.VERSION_PREFIX}${endpoint}`,
      { ...options, headers },
    )

    if (!response.ok) {
      let errorMessage: string
      try {
        const errorData = (await response.json()) as {
          detail?: string
          error?: string
        }
        errorMessage =
          errorData.detail ?? errorData.error ?? JSON.stringify(errorData)
      } catch {
        errorMessage = `HTTP ${response.status}: ${response.statusText}`
      }
      throw new Error(errorMessage)
    }

    return (await response.json()) as T
  }

  private async get<T>(endpoint: string): Promise<T> {
    return await this.fetchWithApiUrl<T>(endpoint, { method: 'GET' })
  }

  private async post<T>(
    endpoint: string,
    data: Record<string, unknown>,
  ): Promise<T> {
    return await this.fetchWithApiUrl<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  // ============ Runs ============

  async getRuns(filters?: RunsFilters): Promise<RunsListResponse> {
    const params = new URLSearchParams()
    if (filters?.status) {
      const statuses = Array.isArray(filters.status)
        ? filters.status
        : [filters.status]
      statuses.forEach((s) => params.append('status', s))
    }
    if (filters?.function) params.append('function', filters.function)
    if (filters?.worker_id) params.append('worker_id', filters.worker_id)
    if (filters?.queue) params.append('queue', filters.queue)
    if (filters?.after) params.append('after', filters.after)
    if (filters?.before) params.append('before', filters.before)
    if (filters?.limit) params.append('limit', String(filters.limit))
    if (filters?.offset) params.append('offset', String(filters.offset))

    const queryString = params.toString() ? `?${params.toString()}` : ''
    return await this.get<RunsListResponse>(`/jobs${queryString}`)
  }

  async getRun(id: string): Promise<Run> {
    return await this.get<Run>(`/jobs/${id}`)
  }

  async getRunStats(filters?: {
    after?: string
    before?: string
  }): Promise<RunsStatsResponse> {
    const params = new URLSearchParams()
    if (filters?.after) params.append('after', filters.after)
    if (filters?.before) params.append('before', filters.before)
    const queryString = params.toString() ? `?${params.toString()}` : ''
    return await this.get<RunsStatsResponse>(`/jobs/stats${queryString}`)
  }

  async cancelRun(id: string): Promise<{ success: boolean }> {
    return await this.post<{ success: boolean }>(`/jobs/${id}/cancel`, {})
  }

  async retryRun(id: string): Promise<{ job_id: string }> {
    return await this.post<{ job_id: string }>(`/jobs/${id}/retry`, {})
  }

  // ============ Workers ============

  async getWorkers(): Promise<WorkersListResponse> {
    return await this.get<WorkersListResponse>('/workers')
  }

  async getWorker(id: string): Promise<Worker> {
    return await this.get<Worker>(`/workers/${id}`)
  }

  // ============ Functions ============

  async getFunctions(type?: FunctionType): Promise<FunctionsListResponse> {
    const params = new URLSearchParams()
    if (type) params.append('type', type)
    const queryString = params.toString() ? `?${params.toString()}` : ''
    return await this.get<FunctionsListResponse>(`/functions${queryString}`)
  }

  async getFunction(name: string): Promise<FunctionDetailResponse> {
    return await this.get<FunctionDetailResponse>(
      `/functions/${encodeURIComponent(name)}`,
    )
  }

  // ============ APIs ============

  async getApiEndpoints(): Promise<ApisListResponse> {
    return await this.get<ApisListResponse>('/endpoints')
  }

  async getApiEndpoint(method: string, path: string): Promise<ApiDetailResponse> {
    return await this.get<ApiDetailResponse>(
      `/endpoints/${method}/${encodeURIComponent(path)}`,
    )
  }

  // ============ Dashboard ============

  async getDashboardStats(): Promise<DashboardStats> {
    return await this.get<DashboardStats>('/dashboard/stats')
  }
}

const conduitApi = new ConduitAPIClass()
export default conduitApi

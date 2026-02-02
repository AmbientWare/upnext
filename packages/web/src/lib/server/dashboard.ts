import { createServerFn } from '@tanstack/react-start'
import conduitApi from '../conduit-api'

export const getDashboardStats = createServerFn({ method: 'GET' }).handler(
  async () => {
    return await conduitApi.getDashboardStats()
  },
)

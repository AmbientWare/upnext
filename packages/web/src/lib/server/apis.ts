import { createServerFn } from '@tanstack/react-start'
import conduitApi from '../conduit-api'

export const getApiEndpoints = createServerFn({ method: 'GET' }).handler(
  async () => {
    return await conduitApi.getApiEndpoints()
  },
)

export const getApiEndpoint = createServerFn({ method: 'GET' })
  .inputValidator((data: { method: string; path: string }) => data)
  .handler(async ({ data }) => {
    return await conduitApi.getApiEndpoint(data.method, data.path)
  })

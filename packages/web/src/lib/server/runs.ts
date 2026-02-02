import { createServerFn } from '@tanstack/react-start'
import conduitApi from '../conduit-api'
import type { RunsFilters } from '../interfaces'

export const getRuns = createServerFn({ method: 'GET' }).handler(async () => {
  return await conduitApi.getRuns()
})

export const getRunsWithFilters = createServerFn({ method: 'GET' })
  .inputValidator((data: RunsFilters) => data)
  .handler(async ({ data }) => {
    return await conduitApi.getRuns(data)
  })

export const getRun = createServerFn({ method: 'GET' })
  .inputValidator((data: { id: string }) => data)
  .handler(async ({ data }) => {
    return await conduitApi.getRun(data.id)
  })

export const getRunStats = createServerFn({ method: 'GET' }).handler(
  async () => {
    return await conduitApi.getRunStats()
  },
)

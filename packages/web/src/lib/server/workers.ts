import { createServerFn } from '@tanstack/react-start'
import conduitApi from '../conduit-api'

export const getWorkers = createServerFn({ method: 'GET' }).handler(async () => {
  return await conduitApi.getWorkers()
})

export const getWorker = createServerFn({ method: 'GET' })
  .inputValidator((data: { id: string }) => data)
  .handler(async ({ data }) => {
    return await conduitApi.getWorker(data.id)
  })

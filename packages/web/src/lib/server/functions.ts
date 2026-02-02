import { createServerFn } from '@tanstack/react-start'
import conduitApi from '../conduit-api'

export const getFunctions = createServerFn({ method: 'GET' }).handler(
  async () => {
    return await conduitApi.getFunctions()
  },
)

export const getFunction = createServerFn({ method: 'GET' })
  .inputValidator((data: { name: string }) => data)
  .handler(async ({ data }) => {
    return await conduitApi.getFunction(data.name)
  })

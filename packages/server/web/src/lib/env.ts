import { createEnv } from "@t3-oss/env-core";
import { z } from "zod";

export const env = createEnv({
  clientPrefix: "VITE_",
  client: {
    VITE_API_BASE_URL: z.string().default("/api/v1"),
    VITE_EVENTS_STREAM_URL: z.string().default("/api/v1/events/stream"),
    VITE_APIS_STREAM_URL: z.string().default("/api/v1/apis/stream"),
    VITE_API_REQUEST_EVENTS_STREAM_URL: z.string().default("/api/v1/apis/events/stream"),
  },
  runtimeEnv: import.meta.env,
  emptyStringAsUndefined: true,
});

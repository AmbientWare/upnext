import { createEnv } from "@t3-oss/env-core";
import { z } from "zod";

export const e2eEnv = createEnv({
  server: {
    E2E_BASE_URL: z.string().url().default("http://localhost:5173"),
    E2E_JOB_ID: z.string().optional(),
    E2E_EXPECT_ARTIFACT: z.string().optional(),
  },
  runtimeEnv: process.env,
  emptyStringAsUndefined: true,
});

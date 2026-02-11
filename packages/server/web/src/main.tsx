import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
  type QueryKey,
} from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";
import { Toaster, toast } from "sonner";
import "./index.css";

const queryErrorLabels: Record<string, string> = {
  dashboard: "Failed to load dashboard stats",
  jobs: "Failed to load jobs",
  workers: "Failed to load workers",
  functions: "Failed to load functions",
  apis: "Failed to load APIs",
};

const getQueryErrorMessage = (queryKey: QueryKey) => {
  const rootKey = Array.isArray(queryKey) ? queryKey[0] : queryKey;
  if (typeof rootKey === "string" && queryErrorLabels[rootKey]) {
    return queryErrorLabels[rootKey];
  }
  return "Request failed. Please try again.";
};

// Configure TanStack Query
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      const message = getQueryErrorMessage(query.queryKey);
      const errorMessage = error instanceof Error ? error.message : "";
      toast.error(message, { description: errorMessage || undefined });
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      const errorMessage = error instanceof Error ? error.message : "Request failed";
      toast.error(errorMessage);
    },
  }),
  defaultOptions: {
    queries: {
      // Data considered fresh for 30 seconds
      staleTime: 30 * 1000,
      // Cache data for 5 minutes
      gcTime: 5 * 60 * 1000,
      // Retry failed requests once
      retry: 1,
      // Don't refetch on window focus by default
      refetchOnWindowFocus: false,
      // Don't refetch in background tabs
      refetchIntervalInBackground: false,
    },
  },
});

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  </StrictMode>
);

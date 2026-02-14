import { createFileRoute, Navigate } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  // Redirect to dashboard
  component: () => <Navigate to="/dashboard" />,
});

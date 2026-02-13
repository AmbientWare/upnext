import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { LiveActivityPanel } from "./-components/live-activity-panel";

export const Route = createFileRoute("/activity/")({
  component: ActivityPage,
});

function ActivityPage() {
  const navigate = useNavigate();

  return (
    <div className="p-4 h-full flex flex-col gap-4 overflow-hidden">
      <LiveActivityPanel
        className="flex-1 min-h-0 flex flex-col overflow-hidden"
        onJobClick={(job) => navigate({ to: "/jobs/$jobId", params: { jobId: job.id } })}
        onApiClick={(apiName) => navigate({ to: "/apis/$name", params: { name: apiName } })}
      />
    </div>
  );
}

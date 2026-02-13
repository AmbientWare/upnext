import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

interface BackLinkProps {
  to: string;
  label: string;
}

export function BackLink({ to, label }: BackLinkProps) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-fit"
    >
      <ArrowLeft className="w-3 h-3" />
      {label}
    </Link>
  );
}

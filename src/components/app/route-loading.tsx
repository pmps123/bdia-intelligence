import { Loader2 } from "lucide-react";

/** Instant pending UI shown while a route segment compiles/loads — avoids a frozen blank screen. */
export function RouteLoading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  );
}

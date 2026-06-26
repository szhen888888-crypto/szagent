import * as React from "react";
import { cn } from "../../lib/utils";

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-24 w-full rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm outline-none transition-colors placeholder:text-zinc-400 focus:border-zinc-400 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

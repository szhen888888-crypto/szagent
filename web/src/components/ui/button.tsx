import * as React from "react";
import { cn } from "../../lib/utils";

type ButtonVariant = "default" | "secondary" | "outline" | "destructive" | "ghost";

const variants: Record<ButtonVariant, string> = {
  default: "bg-zinc-950 text-white hover:bg-zinc-800",
  secondary: "bg-zinc-100 text-zinc-950 hover:bg-zinc-200",
  outline: "border border-zinc-200 bg-white text-zinc-950 hover:bg-zinc-50",
  destructive: "bg-red-600 text-white hover:bg-red-700",
  ghost: "text-zinc-700 hover:bg-zinc-100",
};

export function Button({
  className,
  variant = "default",
  type = "button",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
}) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

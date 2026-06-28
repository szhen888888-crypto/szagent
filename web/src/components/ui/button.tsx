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
  loading = false,
  loadingText,
  disabled,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  loading?: boolean;
  loadingText?: React.ReactNode;
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-md px-3 text-sm font-medium shadow-sm transition-all duration-150",
        "hover:-translate-y-px active:translate-y-0 active:scale-[0.98]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-55 disabled:shadow-none disabled:hover:translate-y-0 disabled:active:scale-100",
        variants[variant],
        className,
      )}
      {...props}
    >
      {loading ? (
        <>
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          {loadingText ?? children}
        </>
      ) : (
        children
      )}
    </button>
  );
}

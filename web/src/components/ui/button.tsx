import * as React from "react";
import { cn } from "../../lib/utils";

type ButtonVariant = "default" | "secondary" | "outline" | "destructive" | "ghost";

const variants: Record<ButtonVariant, string> = {
  default:
    "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-brand-600/25 hover:from-brand-500 hover:to-brand-700",
  secondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200",
  outline:
    "border border-zinc-200 bg-white text-zinc-800 hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-950",
  destructive:
    "bg-gradient-to-b from-red-500 to-red-600 text-white shadow-red-600/25 hover:from-red-500 hover:to-red-700",
  ghost: "text-zinc-600 shadow-none hover:bg-zinc-100 hover:text-zinc-900",
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
        "inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3.5 text-sm font-medium shadow-sm transition-all duration-150",
        "hover:-translate-y-px hover:shadow-md active:translate-y-0 active:scale-[0.98] active:shadow-sm",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none disabled:hover:translate-y-0 disabled:hover:shadow-none disabled:active:scale-100",
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

import { cva, type VariantProps } from "class-variance-authority"
import { clsx } from "clsx"
import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  PropsWithChildren,
} from "react"
import { twMerge } from "tailwind-merge"

export function cn(...values: Array<string | undefined | false>) {
  return twMerge(clsx(values))
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-white/8 bg-[#0c192a]/88 shadow-card",
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 border-b border-white/6 px-5 py-4",
        className,
      )}
      {...props}
    />
  )
}

export function CardContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />
}

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        primary: "bg-cyan-400 text-slate-950 hover:bg-cyan-300",
        secondary:
          "border border-white/10 bg-white/6 text-slate-100 hover:bg-white/10",
        ghost: "text-slate-300 hover:bg-white/6 hover:text-white",
      },
    },
    defaultVariants: { variant: "primary" },
  },
)

export function Button({
  className,
  variant,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>) {
  return (
    <button className={cn(buttonVariants({ variant }), className)} {...props} />
  )
}

export function Badge({
  children,
  tone = "cyan",
}: PropsWithChildren<{ tone?: "cyan" | "green" | "amber" | "slate" }>) {
  const colors = {
    cyan: "border-cyan-400/20 bg-cyan-400/10 text-cyan-300",
    green: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
    amber: "border-amber-400/20 bg-amber-400/10 text-amber-300",
    slate: "border-white/10 bg-white/5 text-slate-300",
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium",
        colors[tone],
      )}
    >
      {children}
    </span>
  )
}

export const inputClass =
  "w-full rounded-xl border border-white/10 bg-[#07111f] px-3.5 py-2.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/10"

export function Field({
  label,
  children,
  hint,
}: PropsWithChildren<{ label: string; hint?: string }>) {
  return (
    <div className="grid gap-2 text-sm text-slate-300">
      <span className="flex items-center justify-between font-medium">
        <span>{label}</span>
        {hint ? (
          <small className="font-normal text-slate-500">{hint}</small>
        ) : null}
      </span>
      {children}
    </div>
  )
}

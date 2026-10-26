// Adapted from shadcn-admin at e16c87f213a5ba5e45964e9b67c792105ec74d26.
// Copyright (c) 2024 Sat Naing. MIT; see notices/shadcn-admin-LICENSE.
// Modified: Sillage tokens, compact variants and explicit native button type.
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib";
const buttonVariants = cva(
  "btn inline-flex items-center justify-center gap-2 disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "btn-primary",
        outline: "btn-outline",
        ghost: "btn-ghost",
        destructive: "btn-destructive",
      },
      size: { default: "", sm: "btn-sm", icon: "btn-icon" },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);
export function Button({
  className,
  variant,
  size,
  asChild = false,
  type = "button",
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      type={asChild ? undefined : type}
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

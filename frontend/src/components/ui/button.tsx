import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import { buttonVariants, type ButtonVariantProps } from "./buttonVariants";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, ButtonVariantProps {}

export function Button({ className, variant, size, type = "button", ...props }: ButtonProps) {
  return (
    <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
  );
}

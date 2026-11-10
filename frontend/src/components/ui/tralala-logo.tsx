import { cn } from "@/lib/utils";
import logoUrl from "../../../assets/logo/Tralala-logo.svg";

/**
 * The Tralala monster. It always stands beside the name, which is what a screen reader reads, so
 * the image itself is decorative. The width and height give the browser the aspect ratio before
 * the file arrives; the class sets the size.
 */
export function TralalaLogo({ className }: { className?: string | undefined }) {
  return (
    <img
      src={logoUrl}
      alt=""
      aria-hidden="true"
      width={1045}
      height={918}
      className={cn("w-auto shrink-0", className)}
    />
  );
}

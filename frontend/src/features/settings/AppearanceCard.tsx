import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { rovingIndex } from "@/components/ui/roving";
import { THEME_KITS, type ThemeKit, type ThemeMode } from "@/themes/theme";
import { useTheme } from "@/themes/useTheme";

const themeChoices: { value: ThemeMode; label: string; description: string }[] = [
  { value: "dark", label: "Dark", description: "Night palette of the chosen theme" },
  { value: "light", label: "Light", description: "Day palette of the chosen theme" },
  { value: "system", label: "System", description: "Follow the operating system" },
];

const kitSwatches: Record<ThemeKit, { background: string; primary: string; accent: string }> = {
  carenomad: { background: "#0a1628", primary: "#4b8bf5", accent: "#34d399" },
  matchmap: { background: "#0b1326", primary: "#ff7043", accent: "#94ccff" },
  classic: { background: "#0b0f14", primary: "#669bff", accent: "#1d9bf0" },
};

/** The arrow keys of a radio group move both ways in either axis, and wrap at the ends. */
const ALONG: Record<string, string> = { ArrowDown: "ArrowRight", ArrowUp: "ArrowLeft" };

interface RadioCardOption<T extends string> {
  value: T;
  label: string;
  description: string;
  /** Drawn before the label; decoration only. */
  preview?: ReactNode;
}

/**
 * A radio group drawn as cards (WAI-ARIA radio group): one Tab stop, the chosen card; the arrow
 * keys move to the next or previous card and choose it, as native radios do; Space chooses the
 * focused card.
 */
function RadioCards<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly RadioCardOption<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const checked = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = rovingIndex(ALONG[event.key] ?? event.key, index, options.length, "horizontal");
    const option = next === null ? undefined : options[next];
    if (next === null || !option) return;
    event.preventDefault();
    buttons.current[next]?.focus();
    onChange(option.value);
  }

  return (
    <div role="radiogroup" aria-label={label} className="mt-3 grid gap-2 sm:grid-cols-3">
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(element) => {
              buttons.current[index] = element;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={index === checked ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`flex items-center gap-3 rounded-lg border p-3 text-left ${
              selected
                ? "border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]"
                : "border-[var(--border)]"
            }`}
          >
            {option.preview}
            <span className="min-w-0">
              <span className="block text-sm font-medium">{option.label}</span>
              <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                {option.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Swatch({ kit }: { kit: ThemeKit }) {
  const swatch = kitSwatches[kit];
  return (
    <span
      aria-hidden="true"
      className="flex h-9 w-9 flex-none items-center justify-center gap-0.5 rounded-md border border-[var(--border)]"
      style={{ background: swatch.background }}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: swatch.primary }} />
      <span className="h-2 w-2 rounded-full" style={{ background: swatch.accent }} />
    </span>
  );
}

const kitOptions: RadioCardOption<ThemeKit>[] = THEME_KITS.map((option) => ({
  ...option,
  preview: <Swatch kit={option.value} />,
}));

/** The theme kit and the mode, saved to the account. */
export function AppearanceCard() {
  const { mode, kit, setMode, setKit } = useTheme();
  return (
    <div className="card-surface p-5">
      <h2 className="text-sm font-semibold">Appearance</h2>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Pick a theme kit, then dark, light or follow the system. Saved to your account, so it
        follows you to any browser.
      </p>
      <RadioCards label="Theme kit" options={kitOptions} value={kit} onChange={setKit} />
      <RadioCards label="Theme mode" options={themeChoices} value={mode} onChange={setMode} />
    </div>
  );
}

2026-10-31

# Theme kits: colour and motion only

## Context

The product should be able to wear the same visual language as the other projects in the family:
CareNomad (midnight navy with periwinkle light) and MatchMap (ink-blue night with ember orange).
Both have a slow, breathing ambient background and a pulsing marker, and both needed a light
counterpart that did not exist before.

The app already had a dark/light/system switch driven by semantic CSS variables, a readable layout
and a font stack that should not change from theme to theme.

## Decision

1. **A theme kit is a palette plus motion, nothing else.** `data-theme-kit` selects `carenomad`
   (default), `matchmap` or `classic`; `data-theme` keeps selecting `dark`, `light` or `system`.
   Typography, spacing and component markup are untouched, so switching themes never reflows the UI.
   `classic` is the palette the app shipped with before the kits: it keeps both modes and hides the
   ambient layer and the pulse entirely, so it stays an option for people who want no motion.
2. **Every kit ships both palettes.** `matchmap` adds a light palette derived from the same orange
   seed rather than reusing the CareNomad light, so each kit keeps its own character in daylight.
3. **One ambient layer, different structure per kit.** `AmbientBackground` renders a grid, a glow
   wash, three blurred colour fields, a particle field and a handful of stars; each kit shows the
   parts that belong to it. CareNomad is a thin *line* grid that breathes over 16 s, with large
   blurred colour fields drifting over 28–40 s and a 5.2 s pulse. MatchMap is a *dot* field plus ten
   glowing particles that twinkle over 6 s (`alternate`) on top of a gradient wash that slides from
   one side to the other over 22 s; it has no blurred colour fields at all, and its wordmark pulse is
   the 2.8 s pin breathe with a halo ping.
4. **Motion is decoration and stays in CSS.** No animation state in React, no timer, and
   `prefers-reduced-motion: reduce` disables every ambient and pulse animation.
5. **Fonts stay as they are.** The kits deliberately do not load web fonts: the app keeps its own
   stack so a self-hosted install makes no third-party requests and the theme switch is instant.
6. **The choice belongs to the account.** `theme_mode` and `theme_kit` are columns on
   `user_credentials` (`GET`/`PUT /auth/preferences`) and travel with `/auth/me`, so one person's
   choice never appears for another. `localStorage` is only a cache for the first paint and for the
   signed-out login screen; on sign-in the stored account value wins, and an account without a stored
   value starts from the default kit instead of inheriting the browser's last choice.

# Design language

Source: the "Break Room Club" system in [Intern-break](https://github.com/Srijjit-V/Intern-break) (public, MIT), read on 2026-11-18 at commit `b944af5`:
`tailwind.config.js`, `src/styles/globals.css`, `src/components/Logo.tsx`, `src/components/ui/*`, `src/lib/use-theme.ts`, `docs/screenshots/arcade.png`.
Tokens live in `viewer/css/styles.css`; `tests/test_design_contrast.py` checks their contrast in both themes.

**What was checked against the source.** The dark theme values, type (Outfit + Plus Jakarta Sans), radius (1.25 rem cards, pill buttons), easing curves and the 480 ms / 180 ms timings in this file match Intern Break's `html.dark` tokens. The light theme was missing and is now added.
**Adopted:** colour tokens (dark and light), type, radius, shadows, motion, eyebrow labels, pill buttons, soft drifting orbs, a sun/moon theme toggle.
**Not adopted:** Tailwind, React and the shadcn-style `ui/*` components (the viewer is a no-build static site, see [ADR-0005](docs/adr/0005-front-end-stack.md)), the dark icon rail (the viewer has one screen with a toolbar), and Intern Break's game-specific art.

## Type
- **Outfit** (500–800) for headings, tight tracking (`-0.03em`). **Plus Jakarta Sans** (400–700) for UI text.
- Scale: 13 px UI text, 15 px body, 20 px stats, 32–56 px landing heading (fluid).
- Numbers use `font-variant-numeric: tabular-nums`. Loading text ends with `…`.
- System fonts are the fallback, so the viewer still works offline.

## Color (dark stage)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#0c0e12` | Page and 3D background |
| `--card` | `#161a22` | Panels |
| `--border` | `#272c38` | Hairlines |
| `--text` | `#f4f6fa` | Primary text |
| `--text-2` / `--text-3` | `#a8b0c0` / `#7c8698` | Secondary / muted text (both ≥ 4.5:1 on card) |
| `--mint` | `#2dd4bf` | Primary actions, focus ring, room box |
| `--hot` | `#fb7185` | Measurements, errors |
| `--amber` | `#fbbf24` | Camera path, warnings |
Primary buttons use dark text (`#07090d`) on mint. Colour is never the only signal: states also change text or shape.

## Spacing and shape
- 4 px base unit; steps 4, 8, 12, 16, 24, 32, 48.
- Cards radius **20 px** (`1.25rem`). Buttons are **pills** (`999px`). Inputs radius 12 px.
- Panels are glass: card colour at 88% with a 12 px blur and a soft shadow.
- Touch targets are at least **44 × 44 px**.

## Motion
- Easing `cubic-bezier(0.22, 1, 0.36, 1)` (out), `cubic-bezier(0.4, 0, 0.2, 1)` (cinema). Enter 480 ms, exit 180 ms.
- Linked cards lift 2 px on hover. Buttons step on hover and press to `scale(0.97)`.
- Background: slow drifting radial orbs (mint, hot, blue), low contrast, 18 s loop.
- Only `transform` and `opacity` animate; no `transition: all`.
- `prefers-reduced-motion` turns the orbs and all transitions off.

## Layout
- The 3D canvas is full-bleed. The panel is a 360 px card on the left (desktop) and a bottom sheet on phones.
- Content max width 1400 px; equal left and right edges; safe-area insets respected.
- Landing: one screen with the header, a one-sentence explanation, a link to the repo and the drop zone.

## Accessibility rules
- Every control is a real `<button>`, `<label>` or `<input>` with a visible `:focus-visible` ring (2 px mint, 2 px offset).
- Keyboard: `M` measure, `P` pick colour, `T` top-down, `R` reset view, `Esc` cancel. A skip link jumps to the viewer.
- Progress and errors are announced with `aria-live="polite"`.
- Pointer-only gestures (drag to orbit, click to measure) have the buttons and keys above as alternatives.

## Themes
- **Dark** is the default and the stage the 3D scene is designed for (`--scene-bg` `#0c0e12`). It does not follow the system setting, because a point cloud reads best on charcoal.
- **Light** is an explicit choice from the sun/moon button in the header, remembered in `localStorage` when it is available. It follows Intern Break's light canvas: `#f4f6fa` page, white cards, `#dde3ec` hairlines, ink `#0e1118`. The 3D canvas becomes `#e9edf4`.
- A tiny classic script (`js/theme.js`) sets the theme before first paint so there is no flash; a module would run too late.
- Every colour in a rule comes from a token (a test fails on a raw colour outside the token blocks; the 3D label pill is the one fixed exception), so a theme can change all of them.

### Light tokens, and where they deliberately differ from Intern Break
Intern Break's own light values fail WCAG 4.5:1 for small text on white, so darker equivalents are used:

| Token | Intern Break light | Contrast on white | Used here | Contrast on white |
|---|---|---|---|---|
| muted text | `#8791a3` | 3.2:1 | `#5f6a7e` (`--text-3`) | 5.5:1 |
| secondary text | `#5a6478` | 6.0:1 | `#4f596c` (`--text-2`) | 7.1:1 |
| mint (links, ring, primary button) | `#0f9f8a` | 3.3:1 | `#0a7466` (`--mint`, white label on it 5.7:1) | 5.7:1 |
| red (measurements, errors) | `#ef4464` | 3.7:1 | `#c0183f` (`--hot`) | 6.1:1 |
| amber (warnings) | `#fbbf24` | 1.7:1 | `#855500` (`--amber`) | 6.4:1 |

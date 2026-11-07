# Design language

Source: the "Break Room Club" system in [Intern-break](https://github.com/Srijjit-V/Intern-break)
(`tailwind.config.js`, `src/styles/globals.css`). This viewer uses its **dark stage** because a point cloud
reads best on charcoal. Tokens live in `viewer/css/styles.css`; a test checks their contrast.

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

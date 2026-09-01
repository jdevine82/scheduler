# Job Scheduler — Style Guide

**Direction:** a clean, light, utilitarian board inspired by Pico CSS's default look — soft neutral grays, a single restrained teal-blue accent, generous whitespace, minimal chrome. Built for readability in a bright workshop or in daylight on a tablet, not a moody dashboard. The Border to Border wordmark (now inverted to solid black) anchors the top bar against the white background.

---

## Color

### Base (light mode)
| Token | Hex | Use |
|---|---|---|
| `--bg-base` | `#FBFCFD` | App background |
| `--bg-panel` | `#FFFFFF` | Sidebar, top bar, modals, cards |
| `--bg-elevated` | `#F3F6F8` | Hovered/active surfaces, day-cell background in week view |
| `--bg-hover` | `#E9EEF2` | Hover state on interactive rows |
| `--border` | `#E2E7EB` | Default hairline borders, hour-grid lines |
| `--border-strong` | `#C7D0D8` | Input borders, focus rings, active borders |

### Text
| Token | Hex | Use |
|---|---|---|
| `--text-primary` | `#24292F` | Headings, primary content |
| `--text-secondary` | `#57606A` | Secondary labels, metadata |
| `--text-muted` | `#8B95A1` | Timestamps, placeholder text |

### Accent
| Token | Hex | Use |
|---|---|---|
| `--accent` | `#1095C1` | Primary buttons, active nav, links, "Book in ServiceM8" CTA — Pico's signature teal-blue |
| `--accent-bright` | `#0D7EA3` | Hover/active state on accent elements, today's date highlight |

### Status colors (used as a left border stripe + small dot + text label on job blocks — never as block fill, so they never fight worker colors)
| Status | Hex |
|---|---|
| Loosely Planned | `#6B7684` |
| Booked with Customer | `#0F766E` |
| Urgent | `#DC2626` |
| On Hold | `#B45309` |
| Completed | `#15803D` |
| Cancelled | `#6B7280` (block also gets a strikethrough on the job number) |

All status colors were chosen to hold at least 4.5:1 contrast against white for the text-label use case, not just as background tints.

### Worker colors (block fill — assigned in order as workers are added, editable per worker)
```
#2563EB  blue
#7C3AED  violet
#0891B2  cyan
#DB2777  rose
#65A30D  lime/green
#B45309  gold        (context makes this unambiguous vs. On Hold status, but avoid assigning both to the same job's most-used lane if it bothers you)
#4F46E5  indigo
#A21CAF  magenta
```
Fill is used at ~14% opacity as the block background (lighter than a dark theme would use, since white needs less tint to stay legible) with a full-opacity left edge in the same color.

---

## Type

- **UI / body:** Inter — clean, high legibility at small sizes, wide language support.
- **Data (job numbers, times, durations):** JetBrains Mono — sets numeric/technical data apart from prose at a glance, the way a dispatch board differentiates job codes from descriptions.

| Role | Font | Size | Weight |
|---|---|---|---|
| Page title | Inter | 20px | 600 |
| Section heading | Inter | 14px | 600, letter-spacing 0.01em |
| Body / job description | Inter | 13px | 400 |
| Job number / time | JetBrains Mono | 12px | 500 |
| Small labels/badges | Inter | 11px | 500 |

No all-caps labels. Sentence case throughout, including badges ("Booked with customer," not "BOOKED").

---

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Job Scheduler        [Month] [Week]      Aug 2026    ⚙      │  ← top bar, 56px
├───────────────┬─────────────────────────────────────────────┤
│  Unscheduled   │   Mon         │   Tue         │   Wed       │
│  (sidebar,     │  D  M  S      │  D  T         │  D          │  ← lane headers: worker initials
│  280px)        │ ┌─┐┌─┐┌─┐     │ ┌─┐┌─┐        │ ┌─┐          │     (only workers with a job that day)
│                │6am│ ││ ││ │   │6am│ ││ │      │6am│ │        │
│  [job card]    │7am│█││ ││ │   │7am│ ││ │      │7am│ │        │  ← block sits in owner's lane
│  [job card]    │8am│█││ ││█│   │8am│ ││ │      │8am│ │        │
│  [job card]    │  ...                                        │
│                │                                              │
├───────────────┴─────────────────────────────────────────────┤
│  ● Dave   ● Mick   ● Sarah   ● Tom          worker legend    │
└─────────────────────────────────────────────────────────────┘
```

- Sidebar fixed-width, left-aligned, always visible.
- Each day column subdivides into vertical lanes, one per worker who has a job that day — width = day column ÷ active lane count. Lane headers (initial + color swatch) stay pinned at the top of the day column as a persistent identity anchor.
- A job with multiple assigned workers appears once per worker's lane, at the same time slot, so both people genuinely see it in their day rather than one owner carrying a small chip for the rest.
- Hour grid lines are hairline (`--border`), with the current-time line rendered in `--accent` on today's column, drawn across all lanes.
- 8px base spacing unit; card padding 12px; block corner radius 4px (kept small and consistent — not the rounded-everything SaaS-card default).

---

## Components

**Job block (week view):** sits inside its worker's lane (position = primary identity signal). Left edge 3px status stripe, background = worker color @ 22% opacity (secondary/reinforcing signal), job number in mono at top, customer name below, status shown as a short text label (colored to match the stripe) whenever the block is tall enough for it — under ~45px tall, only the stripe + a small status dot show, since text won't fit legibly. Jobs with multiple workers render one linked copy per lane rather than a chip — a thin matching outline or subtle connector ties the copies together visually.

**Lane header:** pinned at the top of each day column per active worker — color swatch + initial, ~20px tall, `--bg-panel` background, hairline bottom border.

**Sidebar job card:** flat `--bg-panel` card, hairline border, job number (mono) + customer name + truncated description, drag handle indicated by cursor change only (no visible grip icon needed).

**Buttons:** solid `--accent` fill for primary actions (Book in ServiceM8, Save), outline style (`--border-strong` border, transparent fill) for secondary actions. No gradients, no drop shadows beyond a 1px ambient shadow on modals.

**Status badge:** small pill, colored dot + text, background `--bg-elevated`.

---

## Branding

- **Logo:** Border to Border wordmark. The source asset (`assets/border-to-border-logo.png`) is white-on-transparent; on this light theme it's rendered with a CSS `invert(1)` filter to appear solid black, rather than needing a second logo file.
- **Placement:** top bar, left-aligned, ~26px tall. A hairline vertical divider separates the logo from the app name ("Job Scheduler") shown in `--text-secondary`, so the logo reads as the company brand and the app name reads as the product, not one combined lockup.
- **Clear space:** keep at least the height of the "B" in the logo as empty padding on all sides — don't let the top-bar's other controls (nav toggle, settings gear) crowd it.
- **Don't**: recolor the logo beyond the invert filter, add a drop shadow or glow, or place it on any background darker than `--bg-elevated` — the inverted-black version needs a light surface to read clearly.
- **Favicon/app icon:** crop just the arrow-in-"O" mark (top-left of the wordmark) as a square icon if a favicon is needed, applying the same invert filter (or pre-render a small black PNG once, since favicons don't support CSS filters).

## Principles

1. Color means one thing at a time — worker identity is fill, status is the stripe + text. Never blend the two channels.
2. Numbers get their own typeface. Job numbers, times, and durations are always mono, so they're scannable at a glance the way a real dispatch board's job codes are.
3. Flat and quiet, not glossy. Minimal shadows (Pico's own restraint — a hairline border does most of the work light shadows would), no gradients. This is a tool used quickly, often one-handed, not a showcase.
4. Density is a feature, not a flaw to be hidden — a busy day should look busy (that's real information), but stay legible via lanes/scroll rather than shrinking text.

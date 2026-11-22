# Abhijatri Design System & UI/UX Specification

**Status:** Current as of October 2026.  
**Philosophy:** Contemporary Minimalist, Bangla-First, Offline-Ready Travel Companion for Bangladesh.  
**Companion:** language rules, sitemap and component map are in [`Docs/UI-Architecture.md`](UI-Architecture.md) (F03).  
**Traceability:** Traces to [`Docs/Abhijatri_Project_Proposal.tex`](Abhijatri_Project_Proposal.tex) (O1, O2, O3, O4, O5) and [`Docs/Architecture.md`](Architecture.md).

---

## 1. Aesthetic Direction & Brand Identity

The Abhijatri design system embodies a serene, editorial, and contemporary approach to travel exploration in Bangladesh. It pairs clean Swiss/Scandinavian minimalism with botanical, earthy undertones reflecting Bangladesh's natural landscape (lush hills, mangroves, tea gardens, and sea coasts). 

For nighttime expedition planning, it features an electric **Neon Slate Night Mode** designed for low-light legibility and high visual contrast.

### Core Visual Principles
1. **Utility & Calm:** Spacious layouts, restrained ornamentation, sharp typographic hierarchy, and purposeful chromatic pacing.
2. **No Emojis as UI Icons:** Consistent, crisp SVG iconography (via Lucide React).
3. **Bangla Typographic Elegance:** Dedicated Google Fonts tailored for Bengali conjunct legibility and graceful editorial rhythm.
4. **Tonal Stepping over Drop Shadows:** Minimalist elevation achieved through layered background tones and micro-borders (`1px solid rgba(...)`) rather than aggressive heavy drop shadows.

---

## 2. Color Palettes

> **Superseded again 22 Nov 2026** (Decisions 2026-11-22): white and near-black with one grass green accent; red and amber for alerts only. The tokens are in `frontend/src/global.css`.
>
> **Superseded 4 Nov 2026** (Decisions, "shadcn/ui, Tailwind 4 and a new theme"). The live theme is shadcn/ui stone with a green primary, defined as CSS variables in `frontend/src/global.css`: light background white, text stone-950, primary green-700 (#15803d-equivalent, 5.0:1 with white), borders stone-200; dark background stone-950, cards stone-900, primary green-500 with near-black text. Fonts: Inter (interface, English) and Hind Siliguri (Bangla). Components come from shadcn/ui (`src/components/ui/`) with 44 px minimum targets. The palettes below are kept for history only.


### 2.1 Light Theme (ColorHunt Botanical Sage)
Selected palette based on [ColorHunt #e1f0da](https://colorhunt.co/palette/e1f0dad4e7c5bfd8af99bc85):

| Token Name | Hex Code | Semantic Role |
| :--- | :--- | :--- |
| `canvas-light` | `#F8FAF7` | Base canvas background, prevents optical glare |
| `surface-sage` | `#E1F0DA` | Primary surface tone, hero banners, active tab pills |
| `surface-container` | `#D4E7C5` | Card containers, interactive secondary surfaces |
| `surface-muted` | `#BFD8AF` | Borders, subtle dividers, inactive pills, scrollbar thumb |
| `accent-green` | `#99BC85` | Muted accent, status indicators, secondary interactive |
| `forest-primary` | `#154212` | High-contrast actionable text, primary buttons, logo |
| `forest-container` | `#2D5A27` | Button hover states, prominent headers |
| `on-surface` | `#0E1F12` | High-contrast readable body text (contrast ratio > 10:1) |
| `on-surface-variant` | `#42493E` | Secondary captions, metadata, timestamps |

### 2.2 Dark Theme (Night & Neon Slate)
Night expedition palette with electric signal accents:

| Token Name | Hex Code | Semantic Role |
| :--- | :--- | :--- |
| `dark-bg-base` | `#0B110D` | Obsidian night canvas, zero pure-black glare |
| `dark-surface-1` | `#121A14` | Navigation sidebar, elevated cards, inputs |
| `dark-surface-2` | `#18241C` | Nested cards, hover states, secondary containers |
| `neon-lime` | `#A3E635` | Primary action CTA, active nav indicator, focus rings |
| `pistachio-glow` | `#BEF264` | Secondary neon highlight, key metric numbers |
| `emerald-accent` | `#4ADE80` | Live cache sync dot, verified badges, status pills |
| `on-dark` | `#E1F0DA` | High-contrast light sage typography on dark canvas |
| `on-dark-muted` | `#9CB294` | Dimmed secondary labels, captions, metadata |

---

## 3. Typographic System

All fonts are loaded directly from Google Fonts:

```html
<link href="https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=Noto+Serif+Bengali:wght@400;500;600;700&display=swap" rel="stylesheet" />
```

| Type Role | Font Family | Tracking / Letter Spacing | Purpose |
| :--- | :--- | :--- | :--- |
| **Titles & Headings** | `'Hind Siliguri'` | `-0.01em` | Clean, modern sans-serif for Bangla headlines, section titles, and badges |
| **Body & Regular Text** | `'Noto Serif Bengali'` | `normal` | High-legibility serif for Bangla narratives, descriptions, and guide copy |
| **English & Numerical Data** | `'Inter'` | `-0.06em` (`-60` character spacing) | Ultra-crisp data displays, monetary amounts (`BDT`), timestamps, and English interface |

### CSS Implementation (`src/global.css`)
```css
:root {
  --font-title: 'Hind Siliguri', sans-serif;
  --font-body: 'Noto Serif Bengali', serif;
  --font-en: 'Inter', sans-serif;
  --letter-spacing-en: -0.06em;
}

.font-title { font-family: var(--font-title); }
.font-body { font-family: var(--font-body); }
.font-en, [lang="en"] { 
  font-family: var(--font-en); 
  letter-spacing: var(--letter-spacing-en); 
}
```

---

## 4. Layout & Responsive Architecture

- **Desktop (1024px+)**: Fixed 280px (`w-72`) sidebar with fluid main canvas (`max-w-7xl mx-auto`).
- **Tablet (768px - 1023px)**: Adaptive 2-column card layouts, collapsed sidebar into slide-out drawer.
- **Mobile (< 768px)**: Edge-to-edge touch targets, single-column cards, hamburger navigation, sticky top action bar.
- **Public pages (`/`, `/login`)**: no sidebar. A top bar with the brand, language and theme switches, a centred content column (`max-w-6xl`, sign-in `max-w-md`) and a footer with the 999 emergency line. The landing page shows two path cards side by side on desktop and stacked on mobile; the primary action (Continue as guest) is the filled pill, Sign in is the outlined pill.

---

## 5. Component Specifications

### 5.1 Buttons
- **Primary Action**: Fully pill-shaped (`rounded-full`), `#154212` background with white text (Light) / `#A3E635` background with dark text (Dark). Minimum touch height 44px.
- **Secondary Action**: Pill-shaped with subtle surface background (`bg-surface-sage` or `dark:bg-dark-surface-2`), 1px border.

### 5.2 Tonal Cards (`.tonal-card`)
- `16px` (`rounded-2xl`) corner radius.
- `1px solid var(--color-border-subtle)` micro-border.
- `transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1)`.
- Subtle hover elevation (`translateY(-2px)` with diffuse shadow) **only on cards that are links** (`a.tonal-card`). Forms and content panels do not move on hover: lifting a large card made it jitter when the cursor sat near its edge.

### 5.2a Interactive Selector (`components/ui/interactive-selector.tsx`)
- Expanding photo panels: the open panel grows to seven times the width of the others (`flex 7 : 1`), with a 2px white border (neon lime in dark mode); closed panels show only their icon on desktop.
- 16px (`rounded-2xl`) corners and an 8px gap, matching the tonal cards; a bottom-to-top black gradient keeps white text readable on any photo.
- Phones stack the panels vertically (34rem tall) and keep names visible on closed panels.
- Motion: 700ms ease-out for size and image zoom (110% to 100%), a 120ms-staggered slide-in on load, all disabled under reduced motion.
- Every photo carries its credit pill (top right of the open panel); see `Docs/Image-Credits.md`.

### 5.3 Badges & Status Indicators
- **Bayesian Verified**: Shield icon with emerald green accent.
- **Advisory Warning**: Amber pill with exclamation icon and verification source date.
- **Offline Cache Status**: Animated ping dot with percentage or sync confirmation.

---

## 6. Pre-Delivery Accessibility & Quality Checklist

- [x] Minimum 4.5:1 text-to-background contrast across all Light and Dark modes.
- [x] Visible, high-contrast `:focus-visible` rings for keyboard navigation.
- [x] No emoji as icons (all icons are vector SVGs via Lucide).
- [x] Tap targets $\ge 44 \times 44\text{ px}$ for mobile friendliness.
- [x] Clear bilingual toggle (`বাং / EN`) with Bangla as default locale.
- [x] Real-time diagnostic console to verify backend connectivity.

---

## 7. Frontend API Architecture & Integration Topology

To maintain single-responsibility boundaries and avoid monolithic networking code, client-side API operations are partitioned into focused modules under `frontend/src/api/`:

1. **`client.ts`**: Fetch wrapper: base URL (`VITE_API_BASE_URL`), `Accept-Language` from the interface language, `Content-Type` only when there is a body, and the Platform Foundation 12.3 error body mapped to `ApiError` (`code`, `requestId`, `fieldErrors`).
2. **`health.ts`**: Non-blocking diagnostics pinging `/api/v1/health` (liveness) and `/api/v1/health/ready` (validating database liveness with `SELECT 1`).
3. **`destinations.ts`**: Public destination list and profile reads (R02 API).
4. **`reviews.ts`**: Guest review feed, submission, receipt status and withdrawal; client-side receipt generation.
5. **`index.ts`**: Barrel export (`import { listAllDestinations, submitGuestReview } from '../api'`).

Shared UI states live in `src/components/common/StatusViews.tsx` (loading, error with retry, empty). Destination display components (`RatingSummary`, `AdvisoryCard`, `ProvenanceNote`) live in `src/components/destination/`. Status and evidence: `Docs/Frontend-Implemented.md`.



# Bilingual Information Architecture and UI Component Plan

**Gantt task:** F03, "Create bilingual information architecture and UI component plan".
**Acceptance:** "Bangla-default flows and component map approved". Risk note: "Use system font fallback".
**Status:** Draft for approval, revision 2 (21 October 2026; revision 1 was 20 October). Approver: Shahriar Islam (scope owner). Author: Abdullah Bin Sorwar Choudhury (frontend owner).
**Authority:** Below `Features/Review.md`, `Docs/Security.md` and `Docs/Platform-Foundation.md` (PF; in the repo today at `Features/Platform-Foundation.md`). It describes how the public PWA applies them. API references are to `Docs/api/API.md`. Visual tokens stay in `Docs/Design.md`, which takes the amendment in section 4.4; implementation status stays in `Docs/Frontend-Implemented.md`.

---

## 1. Language model

The rules every screen follows. Section 8 lists where the current build does not yet meet them.

| # | Rule | Source |
|---|---|---|
| L1 | **Bangla is the default.** A first visit renders in Bangla whatever the browser language is. English is one tap away on every screen, including public pages. | Execution.md rule 8; Proposal O1 |
| L2 | **The choice persists and is global.** Stored on the device as `abhijatri_lang`, applied to `<html lang>` before the first request, and sent as `Accept-Language` on every API call so server messages match. Storage may be blocked (private windows, disabled storage): reads and writes are wrapped, and a blocked store means Bangla for this visit, never a blank page. `localStorage` is used because it is synchronous and readable before first render; PF 18.1 names IndexedDB for the language preference, so this choice is recorded in `Decisions.md`. | PF 12.3, 18.1; Security 3.4 |
| L3 | **Switching never loses context.** The same route, scroll position and form input stay, and destination data is not refetched: list and profile payloads carry both languages and do not vary by `Accept-Language` (API 5.12, 5.13). Two things do change: a Turnstile widget re-renders in the new language and needs a fresh token, and a server message already on screen stays in the language it was sent in (L8). | Gantt R03 "English switch preserves context" |
| L4 | **Interface text is always paired.** Every visible string, `aria-label`, `placeholder`, `title` and `alt` has a Bangla and an English form, and the two say the same thing. No English-only labels. A control's accessible name contains its visible text (WCAG 2.5.3). | PF 20; requirement PF-23 |
| L5 | **Maintained content is shown in the interface language with fallback.** The other language is shown only when one is missing, and then that text carries its own `lang`. `pick()` returns only a string, so fallback callers use a variant that also returns the language used. | API 5.12, 5.13 |
| L6 | **User content is never translated.** Reviews, names and notes appear exactly as written. The declared language comes from the text, not the interface (`Frontend-Implemented.md` D12). Each item carries its own `lang`: `BN` → `bn`, `EN` → `en`, `MIXED` → `bn` when the text is mostly Bengali script, otherwise `en`. Banglish in Latin letters therefore gets Latin fonts and no Bengali shaping. | Gantt R09 "Reviews remain in submitted language"; Review.md 3.1 |
| L7 | **Numbers and dates follow the interface language.** Bangla uses `bn-BD` (Bangla digits), English `en-GB`, always through `formatNumber` and the date helpers, including inside `aria-label`. Dates are shown in Asia/Dhaka. Machine values stay Latin: review IDs, receipts, coordinates, codes, endpoint paths. Published phone numbers are shown as published (Latin digits, so they can be copied into a dialer) and always link with `tel:`; Bangla prose may write a short number such as ৯৯৯, but it is still a `tel:999` link. | PF 11.2 |
| L8 | **Server errors are shown as sent.** The API localises `message` by `Accept-Language`; the client branches on `code` only and never rewrites the message. The message is tagged with the language it was requested in, so a switch after the error does not mislabel it. Network failures, which have no server message, use a paired local string. | API 2; PF 12.3 |
| L9 | **No sentence assembly across languages.** Build each full sentence in both languages (`t('৩টি রিভিউ', '3 reviews')`) instead of joining a number and a translated fragment, because word order and plural forms differ. | Bangla grammar |
| L10 | **Product terms are fixed.** The terms in section 1.1 are used exactly, in both languages, on every screen. They carry trust meaning and must never be swapped or merged. | Review.md 2.1, 3.3, 6.1, 6.2, 6.4 |

### 1.1 Fixed terms

| English | Bangla | Rule |
|---|---|---|
| Guest | অতিথি | Never called a member |
| Guest tag | অতিথি `1C669-J0TDY` (Latin letters in both languages) | This browser's public pseudonym, derived on the device from the guest scope secret (Guest-Identity-and-Visits 3.1). Replaced "Guest #N" on 22 Oct 2026. |
| Anonymous guest | বেনামী অতিথি | Second line on a guest review card: "Anonymous guest · 1C669-J0TDY". "Anonymous" means "no account". |
| Member | সদস্য | Signed-in account (R04) |
| Verified Member | যাচাইকৃত সদস্য | Never presented as the same claim as a Verified Visit (Review.md 3.3); Verified Visit is not in the MVP and gets its own term when specified |
| Community Rating | কমিউনিটি রেটিং | Verified Member reviews only, shown from five reviews |
| Guest Feedback | অতিথি মতামত | Separate from Community Rating, never merged |
| Seeded Destination Selection | সম্পাদকীয় সীডেড নির্বাচন | Shown instead of a score below five reviews; labelled as editorial (Review.md 6.4) |
| Advisory | সতর্কতা | Always with source and date |

## 2. Information architecture

### 2.1 Sitemap

```text
Public shell (PublicLayout: brand, language and theme switches, footer with 999)
├── /                 Landing: Continue as guest | Sign in; quick links to destinations
├── /guest            Guest entry: name kept on this device, welcome with the guest tag, 30-day name session, "Start as a new guest", review guide
└── /login            Sign in (disabled until R04)

App shell (AppLayout: sidebar, top bar, session card)
├── /overview                     Overview: counts, destinations with advisories
├── /destinations                 Destination list with bilingual filter
│   └── /destinations/:id         Profile: advisories first, seasonality, guide, restrictions, contacts, reviews
├── /reviews[?destination=:id]    Guest review form, receipt shown once, receipt status and withdrawal
├── /planner                      Prototype (E08)
├── /offline-packs                Prototype (R13)
├── /trips                        Prototype (E09)
└── /health                       System status (diagnostic)

Staff build (separate, admin.<owned-domain>; not in this app; Gate A item)
```

`/guest` is an entry point, never a gate: every app route opens directly for guests (Execution.md rule 1).

Planned public routes, added when their backend or text exists:

| Route | Task | Bilingual note |
|---|---|---|
| `/register`, `/verify-email`, `/reset-password` | R04, R05 | Paired validation and expired-token messages |
| `/account` with "My reviews" and verification request | R05, R07 | Account-only; never cached by the service worker |
| `/privacy`, `/terms`, `/takedown` | Security.md 10.2 public deployment checklist | Versioned and available in Bangla and English with equal prominence (Security.md 3.4); linked from the footer of both shells and from the review notice |

### 2.2 Navigation

| Place | Contents | Bilingual notes |
|---|---|---|
| Sidebar (desktop fixed, mobile drawer) | Overview, Destinations, Cost planner, Offline packs, Saved trips, Reviews, System status; brand links to `/`; session card (guest name and guest tag, Sign in, Sign out) | Labels in the title font; both language forms name the same thing |
| Top bar | Destination search (planned, hidden until it works), API status pill, language switch, theme switch | The language button shows the *target* language ("English" / "বাংলা") and carries that `lang`; its accessible name is that visible word |
| Public top bar | Brand, language switch, theme switch | Same switch component (`PreferenceToggles`) |

### 2.3 Prerendered pages and language

PF 19.2 prerenders destination pages to static HTML, and production CSP forbids inline script (PF 16.3), so the stored preference cannot be applied before the HTML paints. **Recommended:** prerender in Bangla at the existing paths; the app applies a stored English preference on hydration, with the layout reserving space so the switch does not shift content. Separate `/en/...` paths are not added in the MVP. This needs the scope owner's decision and an entry in `Decisions.md` (section 9).

### 2.4 Primary flows

Each flow is complete in either language and survives a language switch at any step.

| Flow | Steps | Bangla-default behaviour |
|---|---|---|
| F1 First visit | `/` → Continue as guest → `/guest` → name → welcome → Write a review or Explore destinations (`/overview`) | Renders in Bangla; the name stays on the device; nothing to accept or sign |
| F2 Shared link | `/destinations/:id` opened directly | No landing gate; prerendered Bangla, then the stored language (section 2.3) |
| F3 Plan a visit | Overview or Destinations → profile → advisories → contacts (`tel:`) | Advisories before attractions; stale advisories shown distinctly with their verified date; dates in Dhaka time |
| F4 Guest review | Profile → Write a review (destination preselected) → form → notice and consent → submit → receipt shown once → done | Review language detected from the text; note sent verbatim; notice in the interface language with a link to the full text; receipt is Latin and copyable |
| F5 Check, withdraw or appeal | `/reviews` → receipt panel → status → withdraw (confirm), or for a rejected review the reason and appeal deadline | Status labels paired; server messages already localised |
| F6 Member sign-in | `/login` (disabled) → Continue as guest | Honest notice in both languages until R04 |
| F7 Verified Member review | As F4 plus photos with alt text | Alt text written by the member in their language, tagged with that `lang` |
| F8 Report a review (planned, R11) | Published review → Report → reason → sent | Reason labels paired (API 5.7); the reported review keeps its own `lang` |

Offline drafts (R15) extend F4 and are planned with their own disclosure text (Security.md 7.4).

## 3. Component map

Each component owns its bilingual behaviour; pages compose them. Status: **Built**, **Partial**, **Planned**, **Prototype**.

| Layer | Component | Purpose | Bilingual responsibility | Status |
|---|---|---|---|---|
| Context | `LanguageContext` | Current language, `t(bn, en)`, persistence, `<html lang>` | L1, L2 (storage not yet wrapped, U12) | Partial |
| Context | `ThemeContext` | Light and dark themes | Same storage rule as L2 (U12) | Partial |
| Context | `SessionContext` | Guest with local name (30-day session) and guest tag; Member and Verified Member from R04 | Session labels per section 1.1 | Partial |
| Layout | `PublicLayout` | Shell for `/`, `/guest`, `/login` | Footer emergency line paired; legal links when the pages exist | Built |
| Layout | `AppLayout`, `Sidebar`, `Navbar` | App shell and navigation | English-only and mismatched labels remain (U4, U5, U9, U10) | Partial |
| Layout | `PreferenceToggles` | Language and theme switches | Target-language label with its own `lang`; accessible name fix (U11) | Partial |
| Common | `LoadingState`, `ErrorState`, `EmptyState`, `describeError` | Shared states | L8; request reference shown in Latin | Built |
| Destination | `RatingSummary` | Community Rating, Seeded Destination Selection, Guest Feedback with counts | L7, L9, L10 (U13) | Partial |
| Destination | `CategoryAverages` | Per-category averages for each audience, never merged | Paired category names; L7 digits | Built |
| Destination | `AdvisoryCard` | Severity, state, validity, source | Paired severity and state labels; dates per L7 | Built |
| Destination | `ProvenanceNote` | Source, publisher, verification date | Publisher name stays as published | Built |
| Reviews | `GuestReviewForm` | Structured review, notice and consent, client checks, retry-safe identity | Language detection (L6); paired field errors; focus to first error | Built |
| Reviews | `CategoryRatings` | Seven categories with prompts | Names and prompts from `GET /review-parameters` | Built |
| Reviews | `TurnstileWidget` | Challenge on guest writes | Widget language follows the interface; re-renders on switch (L3) | Built |
| Reviews | `ReviewPhotos` | Locked for guests; picker for Verified Members | Paired limits and notices; member-written alt text | Partial (upload waits for R07) |
| Reviews | `ReceiptPanel`, `ReceiptStatusPanel` | Receipt shown once; status, withdrawal, appeal deadline | Receipt and IDs Latin (L7) | Built |
| Reviews | `ReviewFeedSection` | Published reviews with paging | L6: each review needs its own `lang` (U3); star label digits (U14) | Partial |
| Pages | Landing, GuestEntry, SignIn, Overview, Destinations, DestinationDetail, Reviews | Route screens | Compose the above | Built |
| Pages | HealthCheck | Diagnostics | Mostly English (U6) | Partial |
| Pages | Planner, OfflinePacks, SavedTrips | Prototypes | English fragments and unlocalised numbers (U7) | Prototype |
| Planned | `AccountForms` (register, verify email, reset) | R05 | Paired validation; paste allowed in password fields (PF 20) | Planned |
| Planned | `OfflineStatus`, `PackCard` | R12, R13 | Freshness and storage-refusal messages | Planned |
| Planned | `ReportDialog` | R11 | Paired reasons (API 5.7) | Planned |
| Planned | `LegalPage` | Security.md 10.2 | One page per notice, versioned, both languages equally prominent | Planned |
| Utilities | `utils/format.ts` (`pick`, `formatNumber`, `formatCalendarDate`, `formatTimestamp`, `currentDisplayDate`, `currentDisplayMonth`) | Locale-aware formatting | L5, L7; add a `pick` variant that returns the language used | Built |
| Utilities | `components/reviews/reviewLabels.ts`, label maps in `AdvisoryCard`, `DestinationDetailPage` | Paired labels for API enums | One map per enum; fallback only where the server sends labels | Built |

### 3.1 How strings are written

- Inline pairs: `t('বাংলা', 'English')` at the point of use. With two languages this keeps both forms together and reviewable; a separate catalogue adds indirection without benefit.
- Labels the server sends win. `GET /review-parameters` returns paired labels for categories, traveller types, comfort tiers and review languages, and the client renders those (API 5.15). The local maps in `reviewLabels.ts` are the offline and error fallback only. Today traveller types and comfort tiers still read the local maps (U15).
- Other enum labels (statuses, severities, advisory states) live in one map per enum as `[bn, en]` pairs and are spread into `t(...)`.
- Bangla copy is written as Bangla, not translated word for word; English is the second form. The two forms make the same promise: a placeholder or label never offers more in one language than the other.
- A string that contains a number is written as a whole sentence in each language (L9) and formats the number with `formatNumber` (L7).

## 4. Typography and fonts

### 4.1 Stacks

| Role | Bangla stack | English stack |
|---|---|---|
| Titles | Hind Siliguri, then system Bangla fonts, then `sans-serif` | Inter, then `system-ui`, then `sans-serif` |
| Body | Noto Serif Bengali, then system Bangla fonts, then `serif` | Inter, then `system-ui`, then `sans-serif` |

**System font fallback (Gantt F03 risk).** Each Bangla stack ends in fonts already on the target devices (PF 19.1), so text is readable before or without the web font: `"Noto Sans Bengali"` (Android), `"Nirmala UI"` and `"Vrinda"` (Windows), `"Bangla Sangam MN"` and `"Kohinoor Bangla"` (Apple). Web fonts use `font-display: swap`.

### 4.2 Font and spacing follow the text's language

The current rule `[lang="en"] { font-family: Inter !important; letter-spacing: -0.06em !important }` matches `<html lang="en">`. Measured in Edge on 21 Oct 2026 (U1): the font does not reach the text, because `body` sets its own `font-family`, so English-mode body text uses Noto Serif Bengali's Latin letters instead of Inter; but `letter-spacing` is inherited, so every element, Bangla included, is tightened by 0.06em (−0.93 px at 15.5 px). Bangla in English mode is visibly cramped.

Planned rule: Inter and its tracking apply only to English text, and Bengali is never tightened.

```css
:lang(en) { font-family: var(--font-en); }
.font-en  { letter-spacing: var(--letter-spacing-en); }
:lang(bn) { letter-spacing: normal; }
```

This depends on Bangla content inside English pages carrying `lang="bn"` (L5, L6). Headings and utility classes follow the same rule: no `tracking-tight`, `tracking-wider` or `uppercase` on Bangla text (U16).

### 4.3 Loading and budget

PF 19.3 allows a subset WOFF2 Bangla web font of at most 40 KiB per weight and at most 2 weights, inside a 100 KiB critical path. Today three families and twelve weights load from Google Fonts twice (`index.html` and an `@import` in `global.css`). Google Fonts also conflicts with the CSP rule `style-src 'self'` (PF 16.3) and is not in the processor register (PF 23.5), so self-hosting is needed before the CSP is enabled, not later.

Planned (F03 follow-up, before the CSP lands):

- Self-host two Bangla weights in total: Noto Serif Bengali 400 for body and Hind Siliguri 600 for titles, each subset and measured against 40 KiB in CI (PF 27). A family whose subset cannot meet the budget falls back to the system Bangla stack, which is the Gantt risk mitigation.
- Self-host Inter 400 and 600, Latin subset only.
- Emphasis in Bangla body text uses the title family at 600; no synthetic bold on Bengali.
- Remove the `@import` and the Google `<link>`s.

### 4.4 Amendment to `Docs/Design.md`

Section 4 changes three things that `Design.md` states, and that file is updated in the same change: fonts are self-hosted, not "loaded directly from Google Fonts"; Inter and its −0.06em tracking apply to English text only, while numbers in Bangla mode use Bangla digits in the Bangla font (L7); the language switch reads "English" / "বাংলা", not "বাং / EN".

## 5. Bilingual layout rules

- Bangla text runs longer and taller (conjuncts, matras). Buttons, pills and the language and theme switches size to content with `min-h-[44px]` (`Design.md` touch target); no fixed widths on text containers; line height at least 1.5 for Bangla body text.
- Never truncate Bangla mid-cluster; use `line-clamp` on whole lines only.
- `uppercase` and `tracking-*` utilities apply only to English text; Bangla has no case.
- Icons sit beside text, never replace it; every icon-only button has a paired `aria-label`.
- Text enlarges to 200 % without loss (PF 20): layouts wrap rather than clip.

## 6. Accessibility in two languages

- `<html lang>` follows the interface language; any element whose text is in the other language carries its own `lang` (switch button, fallback content, user reviews, a server message from before a switch) so screen readers pronounce it correctly.
- An element's `lang` also applies to its `aria-label`, so the two must be in the same language.
- Every input has a visible label or a paired `aria-label`; a placeholder is never the only label.
- Validation messages, live regions (`role="status"`, `role="alert"`) and focus movement are language-independent; the message text is paired.
- TalkBack in Bangla is part of the screen-reader pass required by PF 20.

## 7. Offline and language

- The language preference stays on the device, which PF 18.1 allows; it is not session data and survives sign-out.
- Destination packs (R13) store both languages, as the API sends them, so a pack opens in either language offline.
- Offline and freshness messages are paired local strings, because no server message exists offline.

## 8. Current gaps (audit, 21 October 2026)

Found by scanning every `.tsx` file for unpaired text and attributes, by reading the language and font code against the rules above, and by measuring computed styles in Edge (21 Oct 2026).

| # | Gap | Where | Rule | Fix and task |
|---|---|---|---|---|
| U1 | English mode tightens every element by −0.06em, Bangla included, while English body text does not get Inter | `global.css` `[lang="en"]` on `<html>` | 4.2 | Scope font and tracking by text language (F03 follow-up) |
| U2 | Fonts load twice from Google Fonts, twelve weights, no system fallback stacks; blocks the CSP | `index.html`, `global.css`, `tailwind.config.js` | 4.3 | System stacks and self-hosted subsets before the CSP (F03 follow-up) |
| U3 | Published reviews and fallback content carry the page's `lang`, not their own | `ReviewFeedSection`, `pick()` callers | L5, L6 | Tag each review and each fallback. The feed (API 5.8) has no `language` field, so tag by detected script now and request `language` in 5.8 through the API change process (F03 follow-up) |
| U4 | English-only `aria-label="Toggle Navigation"`; drawer icons not `aria-hidden` | `Navbar.tsx` | L4 | Pair it (F03 follow-up) |
| U5 | English-only brand subtitle "Abhijatri Companion", uppercase with wide tracking | `Sidebar.tsx` | L4 | Pair or drop (F03 follow-up) |
| U6 | System status page mostly English and `toLocaleTimeString()` with the browser locale | `HealthCheckPage.tsx` | L4, L7 | Pair labels; endpoint paths stay Latin (F03 follow-up) |
| U7 | Prototype screens: English fragments ("Airplane Mode Ready", "Saved:", "/ person"), `toLocaleString()` and `toFixed()` without locale, "BDT" prefix only | `OfflinePacksPage`, `SavedTripsPage`, `PlannerPage` | L4, L7, L9 | Fix when each screen is rebuilt (R13, E09, E08) |
| U8 | Coordinates use `toFixed(4)` | `DestinationDetailPage` | L7 | Correct as is: coordinates are machine values |
| U9 | API status pill reads "API Live", "API Offline", "Checking" in both languages | `Navbar.tsx` | L4 | Pair the three states (F03 follow-up) |
| U10 | Search box is not wired, has no label, and its placeholders differ ("রুট বা এলাকা" against "trails, costs"); sidebar item reads "সিস্টেম স্ট্যাটাস" against "API Health" | `Navbar.tsx`, `Sidebar.tsx` | L4, 3.1, 6 | Hide search until it works; align both pairs (F03 follow-up) |
| U11 | Language switch: `aria-label` "ইংরেজিতে দেখুন" overrides the visible word "English" and sits under `lang="en"`; button is 36 px high, theme button about 32 px | `PreferenceToggles.tsx` | L4, 5, 6 | Drop the `aria-label` so the name is the visible word, or put the label in the target language; 44 px targets (F03 follow-up) |
| U12 | `localStorage` read and written without a guard; blocked storage throws on load and the app does not render | `LanguageContext.tsx`, `ThemeContext.tsx` | L2 | Wrap like `api/guests.ts` does (F03 follow-up) |
| U13 | "({n} verified)" joined from a number and a fragment; English term "Editorial seeded selection" differs from "Seeded Destination Selection" | `RatingSummary.tsx` | L9, L10 | Whole sentences; fixed term (F03 follow-up) |
| U14 | Star `aria-label` in Bangla uses a Latin digit and gives no scale ("4 তারকা") | `ReviewFeedSection.tsx` | L7 | `formatNumber` (F03 follow-up) |
| U15 | Traveller types and comfort tiers read local maps although `GET /review-parameters` sends them | `GuestReviewForm.tsx` | 3.1 | Server labels first, local fallback (R09) |
| U16 | `tracking-tight`, `tracking-wider` and `uppercase` applied to Bangla headings and taglines | Landing, Overview, Destinations, DestinationDetail, Reviews pages | 5 | Apply only under `:lang(en)` (F03 follow-up) |
| U17 | First requests can send `Accept-Language: bn` for a stored English preference, because `<html lang>` is set in an effect that runs after child effects and `client.ts` reads it | `LanguageContext.tsx`, `api/client.ts` | L2 | Set `<html lang>` in the state initialiser, or have the client read the stored language (F03 follow-up) |

## 9. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| Q1 | Language of prerendered destination pages (2.3) | Bangla at existing paths; English applied on hydration; no `/en/` paths in the MVP |
| Q2 | Two Bangla web-font weights within PF 19.3 (4.3) | Noto Serif Bengali 400 and Hind Siliguri 600; system font where a subset misses the budget |
| Q3 | Language preference in `localStorage` rather than IndexedDB (L2) | Keep `localStorage`; record in `Decisions.md` |

## 10. Approval

| Role | Name | Decision | Date |
|---|---|---|---|
| Scope owner | Shahriar Islam | Pending | |
| Frontend owner | Abdullah Bin Sorwar Choudhury | Submitted | 20 Oct 2026 (revision 2: 21 Oct 2026) |

On approval, F03 is complete and Q1 to Q3 are recorded in `Decisions.md`. U1 to U6 and U9 to U14, U16 and U17 are implementation items under F03 and Gate A "Bangla and English infrastructure working"; U2 must land before the CSP is enabled. U7 and U15 move with their own tasks; U8 needs no change.

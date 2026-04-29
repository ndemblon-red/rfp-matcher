# Design System Reference

This file contains the complete design system for ADL Catalyst applications. Read this file when building or modifying any template or UI component.

## Table of Contents

1. [Colour Palette](#colour-palette)
2. [Typography & Spacing](#typography--spacing)
3. [Component Patterns](#component-patterns)
4. [Page Layout Pattern](#page-layout-pattern)
5. [UI Decision Rules](#ui-decision-rules)

---

## Colour Palette

The design system uses CSS custom properties with light and dark theme support.

**Light Theme:**
```css
--bg: #F5F6FA;
--bg-raised: #FFFFFF;
--bg-card: #FFFFFF;
--bg-hover: #F0F1F7;
--border: #DFE1EA;
--border-light: #CACDD9;
--text: #0D0B3E;           /* Navy — primary text */
--text-muted: #5A5775;     /* Grey — secondary text */
--text-dim: #8B8AA0;       /* Light grey — tertiary text */
--accent: #0066FF;         /* Blue — primary actions, links */
--accent-soft: rgba(0,102,255,0.08);
--green: #0FA87B;          /* Success, positive indicators */
--green-soft: rgba(15,168,123,0.10);
--amber: #D4870B;          /* Warnings, partial status */
--amber-soft: rgba(212,135,11,0.10);
--red: #D63B3B;            /* Errors, critical flags */
--red-soft: rgba(214,59,59,0.10);
--purple: #8B5CF6;         /* Accents, special indicators */
```

**Dark Theme:**
```css
--bg: #0B0E14;
--bg-raised: #131720;
--bg-card: #181D28;
--bg-hover: #1E2433;
--border: #242B3A;
--border-light: #2A3244;
--text: #E4E8F1;
--text-muted: #8892A6;
--text-dim: #5C6578;
--accent: #4E8AFF;
--accent-soft: rgba(78,138,255,0.12);
--green: #34D399;
--green-soft: rgba(52,211,153,0.12);
--amber: #FBBF24;
--amber-soft: rgba(251,191,36,0.12);
--red: #F87171;
--red-soft: rgba(248,113,113,0.12);
```

---

## Typography & Spacing

```css
--font: 'DM Sans', system-ui, -apple-system, sans-serif;
--mono: 'JetBrains Mono', ui-monospace, monospace;
--radius: 12px;        /* Cards, modals */
--radius-sm: 8px;      /* Buttons, inputs, badges */
--shadow: 0 2px 12px rgba(13,11,62,0.06);
```

Import via Google Fonts CDN:
```html
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..800;1,9..40,300..800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
```

---

## Component Patterns

### Buttons

```css
.btn {
    padding: 8px 18px; border-radius: var(--radius-sm);
    font-size: 13px; font-weight: 700; font-family: var(--font);
    cursor: pointer; transition: all 0.15s; border: none;
}
.btn-primary { background: var(--accent); color: white; }
.btn-sm { padding: 5px 12px; font-size: 11px; }
```

### Cards

```css
.card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px;
}
```

### Filter Buttons (pill-style toggles)

```css
.filter-btn {
    padding: 6px 14px; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.06em;
    border: 1px solid var(--border); border-radius: 6px;
    background: var(--bg-raised); color: var(--text-muted);
    cursor: pointer;
}
.filter-btn.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
```

### Badges

```css
.badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 9px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.05em;
}
/* Semantic colour variants: */
/* background: var(--red-soft); color: var(--red);       — critical/error */
/* background: var(--amber-soft); color: var(--amber);   — warning/partial */
/* background: var(--green-soft); color: var(--green);   — success/compliant */
/* background: var(--accent-soft); color: var(--accent); — info/neutral */
```

### Tabbed Layouts (multi-section pages)

```css
.tabs { display: flex; gap: 0; border-bottom: 2px solid var(--border); margin-bottom: 20px; }
.tab {
    padding: 10px 20px; font-size: 13px; font-weight: 700;
    color: var(--text-muted); cursor: pointer;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
}
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-content { display: none; }
.tab-content.active { display: block; }
```

### Accordion Cards (expandable sections)

```css
.accordion-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 8px; overflow: hidden;
}
.accordion-card.has-content { border-left: 3px solid var(--green); }
.accordion-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; cursor: pointer;
}
.accordion-body { border-top: 1px solid var(--border); display: none; }
```

---

## Page Layout Pattern

Every page follows this structure:
```
Back link → Page title + subtitle → Action buttons → Content
```

---

## UI Decision Rules

Use these rules when choosing layout patterns for a page:

- **Pages with >3 sections** → use tabs
- **Sections with expandable content** → use accordion cards
- **Long lists grouped by category** → use filter buttons
- **Data that loads asynchronously** → show spinner, handle errors inline
- **Modals for detail views** → overlay with backdrop click to close
- **Status indicators** → use semantic colour badges (red/amber/green/blue)
- **Always-visible context** → summary strips at the top of the page

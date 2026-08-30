# components/ — Design System (roadmap #45)

Before phase 7 this item was "a starting point, not the full item":
`src/styles/tokens.css` gave every page the same colors/spacing, but
there was no shared component library and no usage docs — each page
hand-rolled its own `<button>`/`<input>`/`<div className="card">`
markup. This folder is the rest of #45: a small set of real,
reusable React components every page below should use instead of raw
HTML elements, plus this doc.

## Rule

**Reach for a component here before writing a raw `<button>`,
`<input>`, `<select>`, `<textarea>`, or a hand-built table/modal.**
If none of these fit a genuinely new UI shape, it's fine to write
plain HTML for that one case — this is a pragmatic library sized to
this app's actual screens, not a general-purpose UI kit.

## What's here

| Component   | Use for                                              |
|-------------|-------------------------------------------------------|
| `Button`    | Any clickable action. `variant`: primary/danger/ghost. |
| `Input`     | Text/date/password fields, with an optional `label`.  |
| `TextArea`  | Multi-line text, same API as `Input`.                 |
| `Select`    | Dropdowns, with an `options=[{value,label}]` prop.     |
| `Badge`     | Small status pills (`tone`: neutral/success/danger/warning/info). |
| `Card`      | The bordered surface every section sits in, with an optional `title`/`actions` header row. |
| `Table`     | Row/column data (`columns=[{key,header,render?}]`, `rows=[...]`). |
| `Modal`     | Dialogs/overlays (upload forms, confirmations).        |
| `Tabs`      | Sub-navigation within a page (used by Admin Console, Document Center). |
| `Alert`     | Inline error/success/info messages — replaces the old bare `.error-text` paragraphs. |
| `EmptyState`| "Nothing here yet" placeholders, with an optional action button. |
| `Spinner`   | Loading indicator — replaces the old bare "در حال بارگذاری..." text. |

Import from the barrel, not individual files:

```jsx
import { Button, Card, Input } from "../components";
```

## Styling

Every component's visual styling lives in `../styles/app.css` under a
`ds-*` class prefix (`ds-btn`, `ds-input`, `ds-table`, ...) — there is
still only one stylesheet for the whole app, this just adds the
class names the new components render. All of it reads from the same
`tokens.css` variables as before (`--color-primary`, `--radius`,
etc.) — changing a token still re-themes every component and every
page at once.

## Honest limits

- No Storybook / visual test harness — components are documented here
  in prose and by their own prop shapes, not with a live gallery. If
  the component count grows much past what's listed above, that's a
  reasonable next step.
- No automated accessibility audit — basic things are in place
  (`<label htmlFor>`, `aria-selected` on tabs, `aria-label` on the
  modal close button) but this hasn't been run through a screen
  reader or an axe-core pass.
- `Table` and `Modal` are intentionally minimal (no sorting/pagination
  on `Table`, no focus-trap on `Modal`) — every current screen's data
  volume is small enough that this is genuinely enough, not a
  corner cut under time pressure. If a screen ever needs to list
  hundreds of rows, that's the point to revisit `Table`.

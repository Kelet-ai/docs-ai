---
name: docs-ai-integration
description: Use when integrating a docs-ai chat widget into a documentation site or web app. Implement the floating chat chip, streaming chat panel, session management, search integration, and mobile bottom sheet for any framework (React, Astro, MKDocs, Docusaurus, Vue, vanilla JS, etc.)
---

# docs-ai Integration

Integrate a docs-ai-powered chat assistant into a documentation site. Implement idiomatically for the project's existing framework — this spec defines **what to build and how it should behave**, not how to code it.

## Setup — ask first

Before writing any code, ask the user:

> "What is the URL of your deployed docs-ai instance? (e.g. `https://docs-ai.yoursite.com`)"

Then wire it in using the framework's idiomatic environment variable pattern:

| Framework | Env var | How it's read |
|-----------|---------|---------------|
| Vite / Astro / SvelteKit | `PUBLIC_DOCS_AI_URL` | `import.meta.env.PUBLIC_DOCS_AI_URL` |
| Next.js | `NEXT_PUBLIC_DOCS_AI_URL` | `process.env.NEXT_PUBLIC_DOCS_AI_URL` |
| MkDocs / plain HTML | `DOCS_AI_URL` | injected at build time or hardcoded |
| Docusaurus | `DOCS_AI_URL` | `process.env.DOCS_AI_URL` via `docusaurus.config.js` |

Never hardcode the URL. Always fall back gracefully (log a warning) if the env var is missing.

## User Journey

1. User lands on a docs page → sees a floating **"Ask AI"** chip fixed to the bottom-right corner
2. User clicks chip → **chat panel** slides open (bottom sheet on mobile)
3. User types a question, presses Enter → user bubble appears, assistant typing indicator shows immediately
4. First token arrives → typing indicator transitions smoothly to streaming text
5. Stream ends → text is rendered as markdown
6. User asks a follow-up → conversation continues in the same session
7. User clicks **new conversation** → session cleared, ready to start fresh
8. User closes the panel → chip stays visible for re-opening

**Search integration path (optional but recommended):**
User types ≥ 2 chars in the site search dialog → an "Ask AI assistant" chip appears at the bottom of results. Clicking it closes search and opens the chat panel with the query pre-filled.

---

## Features Checklist

### Floating Chip (trigger)
- [ ] Fixed bottom-right, pill shape, chat icon + "Ask AI" label
- [ ] Inherits site's accent/brand color; subtle hover lift
- [ ] Keyboard accessible (Enter/Space activates)
- [ ] Stays visible while panel is open

### Chat Panel — desktop
- [ ] Fixed overlay, ~380px wide, max ~560px tall
- [ ] Open animation: slides up + slight scale-in from bottom-right corner
- [ ] Close animation: reverses on close button, Escape key, or new-session
- [ ] Header: title · new-conversation button (trash icon) · close (✕)
- [ ] Scrollable message list (auto-scrolls to bottom on new content)
- [ ] Input row: auto-resize textarea + send button
- [ ] Footer: "Powered by Docs-AI" with link to the repo

### Mobile Bottom Sheet — ≤640px
- [ ] Full-width, anchored to bottom of screen, rounded top corners only
- [ ] Decorative drag handle pill at top center
- [ ] Slides **up** from bottom on open, slides **down** on close
- [ ] Semi-transparent blurred backdrop behind the sheet
- [ ] Tapping backdrop closes the panel
- [ ] `padding-bottom: env(safe-area-inset-bottom)` for notched devices
- [ ] Body scroll locked while panel is open

### Message Bubbles
- [ ] User: right-aligned, brand color background, white text, flat bottom-right corner
- [ ] Assistant: left-aligned, subtle tinted background, flat bottom-left corner
- [ ] Error: left-aligned, red tint (never raw stack traces)
- [ ] Max width ~85% — long messages don't span the full panel width
- [ ] Markdown rendered in assistant bubbles (paragraphs, lists, code blocks, inline code)

### Loading & Streaming
- [ ] On send: immediately create assistant bubble with **3 small bouncing dots** (typing indicator)
- [ ] On first chunk: replace dots with streamed text — no empty-bubble flash
- [ ] Accumulate raw text during streaming; render markdown **only after `[DONE]`** (not per-chunk)
- [ ] Auto-scroll to bottom as content arrives

### Input Behavior
- [ ] Textarea auto-grows with content (up to ~120px), then scrolls internally
- [ ] **Enter** sends; **Shift+Enter** inserts newline
- [ ] Send button disabled when input is empty **or** while streaming
- [ ] Input cleared and refocused after sending

### Session Management
- [ ] Session ID kept **in memory only** — never localStorage (intentionally lost on reload)
- [ ] Read `X-Session-ID` from the first response header; send it as `session_id` on subsequent requests
- [ ] New conversation: abort any in-flight request, reset session to null, clear message list

### Page Context
- [ ] Extract `window.location.pathname`, strip leading `/` and any `.md` extension
- [ ] Pass as `current_page_slug` in every request so the agent knows which page the user is on

### Public JavaScript Bridge
- [ ] `window.__docsAiChat.open(prefill?)` — opens panel, optionally pre-fills the input
- [ ] `window.__docsAiChat.toggle(prefill?)` — opens if closed, closes if open
- [ ] Required so the search chip (and any other component) can drive the chat

### Accessibility
- [ ] Panel: `role="dialog"`, `aria-modal="true"`, descriptive `aria-label`
- [ ] Message list: `role="log"`, `aria-live="polite"`, `aria-atomic="false"`
- [ ] Focus textarea when panel opens
- [ ] Trigger button keyboard-activatable (not just `div` + click)

### Dark Mode
- [ ] All surfaces, borders, and text adapt to the site's dark theme
- [ ] Verify both light and dark before considering done

---

## Error Handling

| Situation | User-facing message |
|-----------|---------------------|
| HTTP 429 | "Rate limit reached. Please wait a moment before asking again." |
| Network failure | "Network error. Check your connection." |
| Non-2xx response | "Error {status}. Please try again." |
| `{"error": "..."}` SSE event | Show the error text in a red bubble; remove the in-progress assistant bubble |

---

## API Contract

```
POST /chat
  Body:    { message, session_id, current_page_slug }
  Headers: Content-Type: application/json

  Response headers:
    Content-Type:  text/event-stream
    X-Session-ID:  <uuid>   ← read this; pass back as session_id on next request
    Cache-Control: no-cache

  SSE events (blank line between each):
    data: {"chunk": "text delta"}
    data: {"error": "error message"}
    data: [DONE]

GET /chat?q=<query>
  Response: text/plain, stateless, no session
```

**SSE implementation note:** Use `fetch` + `ReadableStream` + `TextDecoder`, **not** `EventSource` — `EventSource` does not support POST. Buffer partial lines across network chunks before parsing.

**CORS:** `allow_origins=["*"]`; `X-Session-ID` is an exposed CORS header, readable by the browser from `response.headers.get('X-Session-ID')`.

---

## Search Integration

Add to the site's existing search dialog:

- Show an "Ask AI" section when the search query is ≥ 2 characters
- Small muted label: "Ask AI assistant"
- Chip button that reads: "Can you tell me about {query}?"
- On click → close search dialog → call `window.__docsAiChat.open(query)`

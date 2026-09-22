# Running axe-core without installing it

The automated pass (Method step 1) needs axe-core. Adding it to a project's dependencies is usually unwanted: it is a dev-time audit tool, not a runtime dependency, and a lockfile change has to be reviewed and justified. Inject it into the running page instead.

This is the default approach when a project has no scanner installed. Check first: if the project already has `@axe-core/cli`, `@axe-core/playwright`, or `pa11y` in its dependencies, use that instead and skip this file.

## Single page

Point a browser automation tool at the page, then evaluate:

```js
await new Promise((res, rej) => {
  const s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/axe-core@4/axe.min.js';
  s.onload = res;
  s.onerror = () => rej(new Error('axe load failed'));
  document.head.appendChild(s);
});

const r = await axe.run(document, {
  runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] }
});

({
  url: location.pathname,
  violations: r.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help })),
  incomplete: r.incomplete.map(i => i.id),
  passCount: r.passes.length
});
```

The `runOnly` tag filter matters. Without it axe also runs best-practice rules that are not WCAG criteria, and the resulting "violations" cannot be cited against a success criterion.

Always report `incomplete` alongside `violations`. Incomplete means axe could not decide, not that the check passed; `color-contrast` lands there routinely when text sits on a gradient, an image, or a translucent layer. Each incomplete item needs a manual check before any conformance claim.

## Whole site

Scanning many URLs by navigating once per page costs two tool calls per page. Instead, load each page into a same-origin iframe from a single host page. Same-origin frames give real layout and computed styles, so contrast rules stay valid.

```js
window.scanViaIframe = async function (path) {
  const f = document.createElement('iframe');
  f.style.cssText = 'position:fixed;left:0;top:0;width:1280px;height:900px;opacity:0.01;z-index:-1;border:0';
  document.body.appendChild(f);
  await new Promise(res => { f.onload = res; f.src = path; });

  const d = f.contentDocument, w = f.contentWindow;
  await new Promise((res, rej) => {
    const s = d.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/axe-core@4/axe.min.js';
    s.onload = res;
    s.onerror = () => rej(new Error('axe load failed in frame'));
    d.head.appendChild(s);
  });
  await new Promise(r => setTimeout(r, 200));

  const res = await w.axe.run(d, {
    runOnly: { type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'] }
  });
  const out = {
    violations: res.violations.map(v => ({
      id: v.id, impact: v.impact, n: v.nodes.length,
      targets: v.nodes.slice(0, 3).map(nd => nd.target.join(' '))
    })),
    incomplete: res.incomplete.map(i => i.id),
    passCount: res.passes.length
  };
  f.remove();
  return out;
};
```

**Inject axe into the frame and call the frame's own `axe`.** Calling the parent's `axe.run()` with a node from another document throws `TypeError: axe.run arguments are invalid`. Passing `iframe.contentDocument` or `iframe.contentDocument.documentElement` to the parent instance fails the same way.

Set an explicit iframe width. Viewport-dependent rules (target size, reflow-adjacent layout) resolve against the frame's box, not the browser window, so an unsized frame gives results for a width nobody uses.

### Long runs

A CDP `Runtime.evaluate` call typically caps out around 45 seconds, which is far less than a site-wide scan needs. Start the loop without awaiting it, then poll:

```js
window.RESULTS = {}; window.DONE = false;
(async () => {
  for (const p of window.ALL) {
    try { window.RESULTS[p] = await window.scanViaIframe(p); }
    catch (e) { window.RESULTS[p] = { error: String(e) }; }
  }
  window.DONE = true;
})();
'started, total=' + window.ALL.length;
```

Then in a later call:

```js
({ done: window.DONE, scanned: Object.keys(window.RESULTS).length });
```

### Survive a host-page reload

Anything on `window` dies if the host page reloads, and on a dev server it will. Hugo, Vite, and webpack dev servers all inject a livereload client that reloads every open page on any file change, including an edit someone else makes while your scan runs. Losing a 274-page run to a one-character commit is avoidable: persist after each page and make the loop resumable.

```js
const KEY = 'axeResults';
const load = () => JSON.parse(localStorage.getItem(KEY) || '{}');
const save = (o) => localStorage.setItem(KEY, JSON.stringify(o));

(async () => {
  const acc = load();
  for (const p of window.ALL) {
    if (acc[p]) continue;                 // resume: skip what's already done
    try { acc[p] = await window.scanViaIframe(p); }
    catch (e) { acc[p] = { error: String(e) }; }
    save(acc);                            // checkpoint every page
  }
  localStorage.setItem('axeDone', '1');
})();
```

After a reload, re-inject axe and the helpers, then re-run the same block: it picks up where it stopped. Clear `axeResults` and `axeDone` before an intentionally fresh run, or you will read a stale scan as a current one.

Neutralising livereload on the host page helps but is not sufficient on its own, since the reload can land between two evaluate calls:

```js
try { if (window.LiveReload && window.LiveReload.shutDown) window.LiveReload.shutDown(); } catch (e) {}
```

Symptom to recognise: an evaluate call returns `Inspected target navigated or closed`, or `window.RESULTS` comes back `undefined` after previously reporting progress. That is a reload, not a finished run. Do not read the empty state as a clean result.

### The host tab degrades over a long run

Each page costs an iframe plus an axe instance, and the cost accumulates. On a run of a few hundred pages the tab slows to a crawl: a rate of roughly two pages per second collapses to one page per 45 seconds, while the dev server still answers in single-digit milliseconds.

Diagnose before assuming the server is at fault. Time a request from the shell (`curl -s -o /dev/null -w '%{time_total}'`); if the server is fast, the tab is the bottleneck. Check `performance.now()` and `performance.getEntriesByType('navigation')[0].type` to confirm whether the page reloaded or has simply been alive a long time.

The fix is to reload the host tab and restart the loop. With localStorage checkpointing the run resumes from where it stopped and speed returns to normal. On a large site, plan to do this every couple of hundred pages rather than waiting for the stall.

### Getting the URL list

Prefer the site's own sitemap over a crawl, so coverage is checkable against a number the site publishes:

```js
window.ALL = await fetch('/sitemap.xml').then(r => r.text()).then(async t => {
  const subs = [...t.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
  const out = new Set();
  for (const s of subs) {
    const x = await fetch(new URL(s).pathname).then(r => r.text());
    [...x.matchAll(/<loc>([^<]+)<\/loc>/g)].forEach(m => out.add(new URL(m[1]).pathname));
  }
  return [...out].sort();
});
window.ALL.length;
```

That two-level walk handles sitemap indexes. A flat sitemap returns its own URLs on the first pass.

### Settle before running, or contrast results are noise

`color-contrast` resolves computed colors against rendered pixels. Run it before webfonts and stylesheets have settled and axe measures a half-painted page, producing contrast failures that do not reproduce. A too-short delay does not fail loudly; it invents findings.

Wait for fonts explicitly, then add a real delay:

```js
try { await d.fonts.ready; } catch (e) {}
await new Promise(r => setTimeout(r, 500));
```

A 120ms settle produced four bogus `color-contrast` pages in a 274-page run; every one came back clean at 600ms, twice. Treat any contrast finding that appears in one pass and not the next as unproven until a second method confirms it.

**Re-verify every flagged page individually before reporting it.** A batch loop is the cheap wide net; it is not the evidence. Re-run each hit on its own with a longer settle, twice, and keep only what reproduces. Findings that survive should also have a named cause (a token, a rule, a computed pair), not just a rule id.

## Validate the harness before trusting it

A scan loop that silently returns empty results looks identical to a clean site. Before reporting anything:

1. Scan one page directly (`axe.run(document)`) and the same page through the iframe harness. The `violations` arrays must match. `passes` counts can differ, because some rules do not apply inside a frame.
2. Confirm the run surfaces at least one violation somewhere, or deliberately break a page (remove an `alt`, drop a label) and confirm the harness reports it.

Without step 2, "zero violations across the site" is unfalsifiable.

## What this does not cover

axe detects roughly a third of AA failures. An injected-axe run replaces neither the keyboard-only pass, the contrast and zoom pass, nor the screen-reader pass. Report it as one pass of four, and never phrase a clean axe run as conformance.

## Network access

The snippets fetch axe-core from a public CDN. On a network without egress, or where pulling third-party script into a page under audit is not acceptable, vendor `axe.min.js` locally and point `s.src` at the local copy. Do not add it to the project's dependency manifest to get around this.

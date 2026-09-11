# RailCall Web Product Demo

Interactive, front-end-only product concept for the RailCall web experience.

## Surfaces

- Homepage: one front door for web and desktop. “Take it for a spin” sends a typed prompt into the same workspace without putting its content in a URL; returning Home preserves the current session. Reloading resets sample state. `?view=chat` opens the web workspace directly.
- Collapsible sidebar: collapse to an icon rail on desktop; independently fold Tools & services, Recent workflows, and Conversations. Recent workflows start folded. Accessible labels remain on rail buttons.
- Integrations: 454 public catalog identities, deduplicated across 35 direct connectors, 412 reachable apps, and 7 additional Marketplace tools. Search covers the entire catalog; routes are separately labeled and filtered, with incremental list rendering. Setup links go to official RailCall sources; nothing is connected, installed, or authorized. Sample source selection propagates to the current task and session ledger. Direct entry: `?view=integrations`.
- Chat: outcome-oriented work with visible but restrained smart-routing economics.
- The right-hand compute calculator keeps savings out of the conversation. Switch between latest request, page session, and browser lifetime; compare online/local charges, edit requests per hour, and inspect work-type totals. Download links and expandable explanations sit beside the numbers. It distinguishes potential savings from savings in local sample scenarios and retains premium API charges. Only aggregate counts and amounts persist in browser storage—never prompts or answers. Storage failure falls back to session-only totals. Each comparison is captured with its run's original source/premium policy; later setting changes do not rewrite it. Figures remain illustrative model/serving charges, not invoices or total ownership costs.
- Workflow library: a persistent, organized full-page list, not a modal. Search/filter saved workflows; open a workflow's Visual, Versions & fingerprint, Runs & evidence, and Permissions & origin. Run an exact historical version or edit its current draft. Start with built-in templates without pretending to install a public package. Direct entry: `?view=library`.
- Studio sections: a Build / Run / Trust / System directory grounded in a read-only review of the installed local Studio. Preview links open implemented demo surfaces; local links require the viewer's own authenticated Studio. Private local workflow contents, credentials, roster, and receipts are not published.
- Builder: action chat expressed as a governed workflow with model escalation rules.
- Builder has two modes: Workflow builder with its own persistent task chat beside the step canvas; Anything builder with page/app/document templates, build chat, preview/source, editable title, version saving, and draft HTML/Markdown export. Draft instructions are recorded, not interpreted by a live model. The mini-app template has interactive sample tasks. Artifact versions are separate from workflow versions and appear in the session ledger.
- Studio opens the workspace-wide Evidence Ledger: requests, runs, processing steps, approval holds and decisions, blocked actions, workflow versions, connection choices, and policy changes. Search/filter all events, inspect evidence, and export the matching ledger with linked runs and versions. Direct entry: `?view=activity`.
- Studio workbench: enter with “Look under the hood” on any Chat result; select runs, inspect individual execution steps, check transactions and their costs, view the saved policy, approve or reject sample actions inline, export run JSON, and return to the same task in Chat or Builder. On first entry with no existing runs, three labeled examples populate the session. Use `?view=studio` for the direct entry.
- Marketplace: 47 real public listings captured September 10, 2026 from the RailCall creator API; filter by type/department and open the actual public listing. This is a dated snapshot, not a live feed. Details, licensing, checkout, and installation stay on railcall.ai. Studio's built-in examples are separate and never claim Marketplace installs.
- Railhub: organization services for uptime, internal routing, a centralized ledger, and a shared library, with a link to Railhub.ai. All four use restrained product-native visuals: an execution timeline, capacity indicators, unsigned action records, and an organized versioned workflow list. Examples are labeled and rendered identically on the homepage, in the app, and in service details. The earlier decorative 3D assets are preserved in source but no longer included in the public build.
- Homepage visual story: the full web workspace and compute sidebar lead the hero, using the user-supplied screenshot as the product reference. Immediately below, Studio / Workflows / Cryptographic receipts tabs use real captures: the public Studio builder image, the workflow library at 02:00 of the supplied investor demo, and its recorded Studio receipt at 01:24. Captions distinguish the signed recorded receipt from this web preview's sample runs. The remaining routing, integrations, Marketplace, and Railhub sections are unchanged. Rejected generated artwork is not published.

Product images are expandable interactive previews. The hero uses a larger desktop column; the library and receipt captures are framed around the actual interface using CSS, preserving original pixels and labels. Click any image to inspect it in a native dialog with four-screen navigation, fit/native/150%/200% zoom, keyboard navigation, and a direct action into the matching workspace. Original recorded receipts remain distinguished from preview evidence.

Local checks: `node model.test.cjs`, `node navigation.test.cjs`, `node home.test.cjs`, `node economics.test.cjs`, and `node product-screens.test.cjs`. These are source-level tests, not browser QA. Superseded image-generation prompts and asset paths are recorded in `IMAGE-PROMPTS.md`.

Execution usage, savings, responses, routing, run receipts, and upgraded services remain illustrative. Marketplace listing metadata and prices are actual public snapshot data and may change. Workspace content resets on reload; only aggregate demo savings totals persist on this browser until site data is cleared. Lifetime is not account-wide. The signature laboratory uses a real signature over a synthetic public specimen; it does not certify the preview's runs. Local Studio is not paired or synchronized.

Brand reference: RailCall's public light theme, official logo, Montserrat and Geist Mono, white/charcoal surfaces, pink #d6004a and the pink/orange brand gradient. The catalog uses the public Marketplace's cool neutral surfaces. Marketplace does not permit embedding or cross-origin API reads from this preview; no proxy or policy bypass is used.

Read PRODUCT-DIRECTION.md for the product model, limitations, and implementation sequence. Source entrypoints are index.html, workspace.css, model.js, and workspace.js; studio.css and studio.js contain the Studio workbench. Run `node model.test.cjs` for the bounded model/signature/static checks. No application dependencies are required.

Homepage and integration design were reviewed through 10 bounded research/source-review tasks. Research references: https://railcall.ai/, https://railcall.ai/integrations/, https://railcall.ai/docs/studio/, https://railcall.ai/downloads/chat/, https://railcall.ai/pricing/, https://railcall.ai/railhub/, https://claude.com/, https://lmstudio.ai/, and https://ollama.com/. Product claims are scoped to eligible local work, not guaranteed savings or universal audit completeness. Browser web-app pairing remains product direction, not a shipped backend.

## Run locally

From this project directory:

```bash
python3 -m http.server 4173
```

Then open `http://127.0.0.1:4173`.

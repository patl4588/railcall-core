# RailCall: one workspace, different depths

Start with a conversation. Make useful work repeatable. Inspect its execution when needed. The user should never have to move information manually between three unrelated products.

Positioning: not just one model—the right intelligence for the job. The product direction combines models, relevant web information, connected knowledge, and tools, selecting a suitable route for each step under the user's quality and data constraints. Speed and cost improvements are goals that require evaluation, not unconditional performance claims. It does not imply access to every model, the entire internet, private sources without authorization, or all available knowledge.

The local-compute ambition is to handle 90% of routine requests locally with no hosted model charge for fully local work. The homepage explicitly labels this a product target, not a measured result or universal free-usage guarantee. Validate it against a defined workload, hardware profile, quality threshold, and dated test results before presenting it as achieved. Do not use it as the basis of the preview's per-run cost calculations.

## The composition

The homepage borrows the public RailCall site's visual identity and local-freedom story: a bold gradient headline, type-to-enter composer, one product stage, visible computer routing, and an explicit free local suite. “Free” refers to local Chat, Builder, and Studio with no hosted AI charge for fully local work; it does not erase hardware, energy, third-party, or optional hosted costs. Web pricing is not finalized in this concept.

The integration directory contains 454 distinct catalog names verified on September 10, 2026: 35 direct connector entries and 412 reachable app entries from [RailCall's public directory](https://railcall.ai/integrations/), plus seven non-overlapping tools from public Marketplace listings. The additional tools are Zernio, Google Ads, Freelancer.com, Odoo, Feishu Bitable, SingleOps, and Google Sheets. “450+ integrations” describes this combined ecosystem, not 450+ native connectors or tested authorizations. Some tools have several access routes; each name is counted once. The public page's older header count is not used.

Computer routing is a first-class visual explanation: select a local, approved organization, or RailCall-hosted scenario and optionally add premium review. The diagram shows why that route fits and makes the external data/cost boundary explicit. It remains an illustration, not hardware discovery, device pairing, or policy enforcement.

Each Railhub service uses a restrained product-native visual: an execution timeline, an organization capacity view, unsigned action records, and an organized versioned workflow list. All are labeled examples, not live infrastructure status, audited production records, or certification claims. These replace the earlier decorative 3D imagery.

Chat is the everyday entry point: answers, drafts, and running saved workflows. Builder is an editor for the steps behind that work. Studio supplies the connections, permissions, schedules, approvals, routes, receipts, and deeper inspection. Its controls appear beside the relevant step or result; its full local interface remains available for operators.

A workflow is a versioned object shared by these surfaces, not a fourth place the user has to learn. Marketplace supplies reusable workflows and modules. Users review access, import a version into their library, customize it in Builder, and run it from Chat. Optional NFT provenance belongs inside package details and creator publishing, never in the basic conversation flow.

Railhub is the organization-services layer. It lives inside the app with a click-through to [Railhub.ai](https://railhub.ai/). Its initial offerings are:

| Service | Where it belongs in the existing experience |
| --- | --- |
| 24/7 uptime | Beside schedules and execution location: keep approved work running when a desktop is offline. Define a real availability commitment, durable queues, retries, failover, and recovery procedures. |
| Internal capacity routing | Beside compute controls: use approved organization computers and servers according to data policy, capability, memory, availability, queue depth, and cost. External overflow needs explicit permission. |
| Centralized cryptographic ledger | Beside Studio receipts: aggregate signed records, identify signers, verify integrity, expose evidence gaps, and export a trace for agency review. |
| Centralized workflow library | Beside saved workflows and Marketplace: publish reviewed versions, control access, track changes, and make approved work available to the organization. |

These services extend the same task, workflow, and execution records. They must not create another disconnected control panel. The browser and desktop are execution choices within this product, not separate histories.

## What this interactive preview actually does

The workflow library is a standard workspace destination, separate from Railhub's organization-wide library upgrade. It uses organized rows with name/origin, run status, version/trigger, and Run/Visual/Edit controls. A row opens a full-page workflow visual with inline version fingerprints, exact-version runs, evidence links, and permissions. The old organization-library popup has been removed.

A read-only inspection of local Studio confirmed the product's Build, Run, Trust, and System organization: Builder/Canvas, Workflows, Marketplace, Modules, Licenses, Integrations; Monitor, Schedules, Webhooks, Approvals; Runs, Policy, Audit; Router, Team, Organization, Settings. The Studio sections directory retains this map. Browser previews are explicitly separate from features requiring the local runtime; no local private catalog, keys, roster, or production evidence is copied to the public artifact. Navigation inspection did not execute workflows, approve writes, edit credentials, or change local policies.

Chat, Builder, Studio, and Railhub share one in-memory workspace model. A conversation becomes a draft; a saved version runs from Chat; approvals append decisions to the same event history shown in Studio. Every follow-up request is recorded and linked to its run. Saved versions and run snapshots retain inputs, routing, and policy after draft changes; replay uses the exact inspected snapshot rather than the latest version. Credit uses those same runs.

Studio's default view is the workspace-wide Evidence Ledger, not an isolated run. It collects conversations, workflow edits and saves, connection choices, routing policies, processing, approvals, and held/blocked actions. Search, category/location filters, current-review and historical-block filters, event details, per-run deep links, and JSON export all use this shared history. Historical approval requests are retained after decisions. Preview records are unsigned; the real local Studio is not connected.

Marketplace is the existing public catalog at https://railcall.ai/marketplace/, shown here as a dated snapshot of 47 actual listings (35 modules, 12 workflows). Search, filters, and listing links use real metadata. The public site owns details, licensing, checkout, installation, requests, community, and seller flows. Its embedding and cross-origin restrictions are respected. A production live catalog needs an approved API integration; this static preview does not claim one. Built-in Studio examples are labeled separately and never masquerade as Marketplace installations.

Studio now presents a run-history rail, an interactive execution trace, and a step inspector with Output, Transactions, and Policy views. “Look under the hood” on a Chat result opens that exact run; “Check transactions” shows its processing records, costs, proposed action status, and receipt. These are usage/action records, not on-chain transfers or actual payments. An approval can be handled inline, immediately updating the downstream step and the same conversation record. Users can export a run, inspect its routing, or continue the work in Chat and Builder. Opening an otherwise empty Studio loads three labeled example workflows/runs into the same session; opening it again does not duplicate or charge them again. The examples do not overwrite existing work or manufacture verified production evidence.

Workspace state resets on reload. Responses, execution events and charges, connection settings, subscriptions, schedules, and organization services are examples. Public Marketplace metadata and prices are real snapshot data, not guaranteed current. The local Studio is available through an optional local frame or separate launch link, but the preview is not authenticated or synchronized with it. Loading that frame does not establish a trusted connection.

The signature lab verifies a real Ed25519 signature on a clearly synthetic bundled specimen, using only a demonstration public key. Changing its cost invalidates that signature. The interactive run records are unsigned; they are never mislabeled as production receipts. There is no mint, live provider call, external send, payment, installation, or organization membership change.

## Shared execution contract

Every saved workflow has an accessible `# Workflow fingerprint` control in the library, Builder, and Studio. It computes SHA-256 over that exact version's canonical preview definition. A run's fingerprint uses its captured version, not the latest edited draft. The fingerprint links to the related run transactions when available. It identifies content and must not be presented as a signature, ownership claim, or proof of correct execution.

Implement a shared control plane with stable organization, task, workflow, workflow-version, run, step, connector, policy-version, and signer-key identifiers. Every result should point to the exact immutable definition, inputs, and policy used. Distinguish an editable draft from an approved version; changing a draft must not mutate a past run or silently update an existing schedule.

Execution adapters can target a paired local Studio, RailCall-operated infrastructure, organization-owned capacity, or an approved model API. The user-facing surfaces read the same run stream. The server or device enforces permissions, budgets, approvals, idempotency, cancellation, and data policy; browser controls alone are not enforcement.

Local pairing requires authenticated, narrowly scoped access, origin validation, explicit user consent, replay protection, and revocation. Never expose an unauthenticated localhost service to the public web. Credentials and private signing keys remain with the trusted executor, not in the hosted page.

## Cryptographic receipts and agency auditability

Each trusted executor signs a canonical, versioned record binding the run and step IDs, workflow and policy hashes, input/output references or approved digests, measured usage, route decisions, approval evidence, and relevant time and sequence information. A parent receipt binds the child receipts and their signers. A central ledger verifies and indexes these records; it does not replace the underlying signed evidence.

Full auditability needs more than valid signatures: authenticated signer identity, complete event capture, gap detection, replay/deduplication handling, immutable or independently anchored checkpoints, retention and export policy, key rotation/revocation, access control, and agreement about which systems and time ranges are covered. Show missing records and unverifiable evidence explicitly. A signature establishes integrity and key possession, not the truth of every statement made by its signer or completeness of the ledger. Provider billing and usage evidence should be reconciled rather than trusting client-calculated costs.

Use an agreed canonicalization specification and cross-language test vectors. The fixed demonstration specimen uses sorted ASCII JSON keys and string costs; that is not a complete production canonicalization standard. See the [Ed25519 specification](https://www.rfc-editor.org/info/rfc8032/).

## Routing and economics

Choose the lowest-cost route that meets an explicit quality, latency, privacy, and reliability requirement. Prefer deterministic tools and validated cache hits when applicable; evaluate eligible open models on actual task families; escalate to a more capable model when evaluation or policy requires it. Do not promise a universal 90/10 routing split or infer quality solely from a model's self-reported confidence.

RailCall-operated servers still incur hardware, utilization, energy, networking, queueing, redundancy, support, and operations costs. Desktop work also consumes real hardware and electricity. Local deployment can eliminate a cloud-model charge for an eligible step; it does not make all work free. Premium API costs can dominate even when most steps are local.

The UI compares the same example route before and after moving eligible steps, states what is excluded, and leaves premium charges visible. Any future direct-provider comparison should use equivalent workloads and quality targets, with dated prices. Wholesale discounts are not assumed until contracts exist. Trial credit is a product allowance with an acquisition cost, not a deposit of provider tokens. Meter the actual cost basis, impose budgets and abuse controls, and set allowances after measuring unit economics.

Savings belong beside the work, not inside each answer. The sidebar separates latest-request, session, and browser-lifetime aggregates, with an editable hourly workload projection. Potential savings are the same-workload online/local difference; local-scenario savings are a subset, not an additional amount. Neither is real financial telemetry in this preview. Anything-builder work is explicitly unmetered rather than assigned fabricated savings. Only aggregate demo counts and amounts are stored locally. The 90% local-handling target does not enter any calculator formula.

Model provisioning should select a suitable, licensed model for the device and obtain download/storage consent. It should not automatically download every available model. Internal organization routing requires approved node registration, availability and capability reporting, tenant isolation, and policy enforcement before any job is assigned.

## Marketplace, workflow library, and optional NFTs

Marketplace is discovery. The organization library is the reviewed, permissioned collection a team runs. Imported packages should carry a manifest with version, content hashes, publisher/signature identity, declared permissions, dependencies, license, compatibility, and review status. Pin approved versions; review updates rather than silently pulling new code. Treat third-party workflow instructions and modules as untrusted inputs.

An optional NFT can reference a released package and its provenance. It is separate from per-run receipts, and is not required to use or verify a workflow. Token ownership alone should not be represented as copyright ownership, a software license, account access, or proof that an execution occurred. Keep those terms and access grants explicit. See the [ERC-721 token and metadata standard](https://eips.ethereum.org/EIPS/eip-721).

## Next implementation sequence

1. Define the shared run contract and connect Chat, Builder, and the actual local Studio to it.
2. Add authenticated device pairing, scoped connectors, execution policy, approvals, and reliable event delivery.
3. Support immutable workflow versions and reviewed Marketplace imports; add the organization library and authorization.
4. Implement signed execution evidence, independent verification, ledger coverage checks, and agency exports.
5. Measure quality and all-in cost per task; then set credit allowances, pricing, escalation policy, and service commitments.
6. Add managed uptime and internal capacity routing with tested recovery and tenant boundaries. Keep NFT publishing optional and independent.

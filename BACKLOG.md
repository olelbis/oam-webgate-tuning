# Backlog

Suggested improvements, roughly ordered by value/effort ratio. None of these
are required for the tool to be useful today; they are candidates for future
releases.

## High value

- **Multi-farm / multi-WebGate topologies (promoted after real-world use).**
  Real deployments register several agents against the same OAM cluster
  (e.g. Apache intranet + Apache extranet + OHS for OIDC/federation), each
  with its own MPM block, instance count, and WebGate profile. Today the
  script models one homogeneous farm per run, so the per-Access-Server load —
  which is the sum of ALL agents — must be added up by hand. Planned design:
  accept a topology file (YAML/JSON) with a list of agents, each carrying
  `name`, `conf` (or explicit MPM values), `instances`, `conn_per_oam`; the
  script computes per-agent projections and the aggregated per-Access-Server
  total, applying warning thresholds to the aggregate (the only number that
  matters). CLI stays available for the single-farm case.
- **Report output with the suggested configuration.** Emit a ready-to-share
  rollout report (Markdown, `--report out.md`): current vs suggested values
  per WebGate profile, the projection table with explicit arithmetic, an
  application order, and a monitoring checklist (DMS Spy OAMProxy metrics:
  active connections as open−closed, isAuthenticated/isAuthorized latencies,
  proxy maxActive threads). Requires accepting the *current* profile values
  as optional inputs so the report can show the delta, not just the target.
- **User-capacity estimate: to be evaluated — feasibility not established.**
  Estimating "how many users" a given configuration sustains is NOT derivable
  from MPM blocks and connection counts alone: it depends on authentication
  rate (logins/sec, not registered users), OAP request latency, WebGate cache
  hit ratio, LDAP and OAM server capacity. Oracle's own published figures
  (e.g. the 12.2.1.4 performance white paper) come from load benchmarks on
  specific hardware shapes, not from formulas. A future version could offer a
  rough throughput *bound* (e.g. requests/sec ceiling from measured OAP
  latency × available connections) clearly labeled as an upper bound, but
  only if it can be done without inventing numbers. Until then the honest
  answer is: measure with a load test.
- **Resolve `Include`/`IncludeOptional` directives in `--conf`.** Today the
  parser reads a single file; real-world configs (RHEL `conf.modules.d/`,
  Debian `mods-enabled/`) split the MPM block away from httpd.conf. Following
  includes (with glob support and a recursion cap) would make `--conf` work
  out of the box everywhere.
- **`--json` output mode.** Emit the computed profile and projections as JSON
  so the tool can be consumed by automation (Ansible/Chef pipelines, CI checks
  on config repos, monitoring annotations).
- **Prefork MPM support.** With prefork every process is single-threaded and
  runs its own WebGate, so the multiplier becomes `MaxRequestWorkers` itself —
  a dramatically different (and dangerous) sizing. Detecting prefork and
  applying the right formula, with a loud warning, would prevent the most
  common sizing mistake of all.
- **Per-web-server heterogeneous farms.** Accept a list of MPM configs (or
  multiple `--conf` files) and sum the per-Access-Server load across different
  Apache configurations, instead of assuming an identical farm.

## Medium value

- **Server-side capacity awareness (OAM 12c only: OAPAccessWM / AccessCapacity).**
  On OAM 12.2.1.3/12.2.1.4, inbound OAP requests are governed by the
  `wm/OAPAccessWM` work manager with a fast-fail `AccessCapacity` constraint
  (queued + executing requests; historical defaults: 10 pre-BP
  12.2.1.3.210915 / 12.2.1.4.210920, 300 afterwards, tunable via console →
  Plan.xml — see MOS Doc ID 2897837.1). The script could accept an optional
  `--access-capacity N` and compare it against the projected per-AS
  connection ceiling, warning when the margin is thin, and emit the
  diagnostic symptoms in the checklist ("AccessCapacity rejected request...",
  cluster OVERLOADED state, WebGate "unable to contact any Access Servers")
  plus the cluster caveat that Plan.xml must live on shared storage.
  IMPORTANT version gate: this mechanism reportedly no longer exists from
  OAM 14c — the feature must be version-aware and clearly labeled 12c-only;
  the 14c replacement (if any) is unverified and must be researched first.
- **Reverse mode ("budget mode").** Given a maximum number of OAP connections
  each Access Server can sustain, work backwards to the maximum viable
  `conn-per-oam` / children combination, instead of only validating forward.
- **OHS awareness.** Oracle HTTP Server ships its MPM settings in the same
  syntax but different default paths; adding `--ohs-home` auto-discovery of
  the right file would simplify usage on OHS installs.
- **Warning for oversized `MaxRequestsPerChild`/`MaxConnectionsPerChild`
  interaction.** Estimate the OAP reconnection burst caused by child recycling
  at a given request rate, and flag configurations where recycling storms are
  likely.
- **Unit tests + CI.** A pytest suite covering the parser (worker/event
  blocks, 2.2/2.4 names, comments, global fallback) and the math, wired to a
  GitHub Actions workflow with a lint step (ruff).

## Low value / nice to have

- **`--markdown` report output** ready to paste into a change request or wiki
  page, including the worked table from the README.
- **Interactive TUI polish** (colors, summary table) via `rich`, kept behind
  an optional dependency so the stdlib-only path still works.
- **i18n of the output** (English default, Italian available) via a simple
  message catalog.
- **Packaging** as a pip-installable console script (`pipx install
  oam-webgate-tuning`).

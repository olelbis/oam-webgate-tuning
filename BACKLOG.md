# Backlog

Suggested improvements, roughly ordered by value/effort ratio. None of these
are required for the tool to be useful today; they are candidates for future
releases.

## High value

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

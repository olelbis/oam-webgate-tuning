# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-07-13

### Fixed
- Require an explicit `--mpm worker` or `--mpm event` selection when both
  worker and event MPM blocks are present in the parsed Apache configuration.
- Parse only the selected active MPM block when `--mpm` is provided, avoiding
  mixed values from multiple MPM configurations.
- Validate numeric inputs so invalid zero or negative topology and MPM values
  fail before calculations are performed.

## [1.0.0] - 2026-07-10

### Added
- Core calculator: derives `max_children` from the MPM block
  (`min(MaxClients/ThreadsPerChild, ServerLimit)`) and computes the suggested
  WebGate profile: *Max Number of Connections*, *Max Connections* (sum of
  primaries only), *Failover Threshold*, *AAA Timeout Threshold*.
- OAP connection projection: at startup (StartServers), at full load per web
  server, farm total, and per single Access Server.
- MPM block validation with warnings: ServerLimit choking MaxClients,
  oversized ServerLimit (wasted scoreboard memory), ThreadLimit lower than
  ThreadsPerChild (silent capping), ThreadLimit == ThreadsPerChild rigidity,
  MaxSpareThreads below the `MinSpareThreads + ThreadsPerChild` floor.
- Load thresholds per Access Server (warning ≥ 300, critical ≥ 800),
  configurable via `WARN_CONN_PER_AS` / `CRIT_CONN_PER_AS`.
- Secondary Access Server support: applies the A-Team rule
  *Failover Threshold = Max Number of Connections* when secondaries exist.
- Three input modes: interactive prompts with sensible defaults, full CLI
  flags, and `--conf` to parse the MPM block straight from an httpd.conf
  (worker and event, legacy 2.2 and 2.4 directive names, commented lines
  ignored, global-level fallback when no IfModule block is present).
  Explicit CLI parameters always take precedence over file values.
- Final checklist in the output: Access Server sizing with headroom for
  reconnection bursts, farm consistency check, load-test monitoring command
  (`ss -tan | grep 5575`), child-recycling caveat.
- Sample configuration in `examples/httpd.conf.sample` matching the worked
  example in the README.
- Documentation: README with the origin of the calculation (Oracle A-Team,
  "OAM 11g Webgate Tuning") and a step-by-step, foolproof walkthrough of how
  the final result is obtained.

[1.0.1]: https://github.com/olelbis/oam-webgate-tuning/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/olelbis/oam-webgate-tuning/releases/tag/v1.0.0

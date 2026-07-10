#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webgate_tuning.py — OAM WebGate tuning calculator for Apache/OHS (worker/event MPM)

Based on the logic of the Oracle A-Team article "OAM 11g Webgate Tuning":
  - the WebGate module is instantiated by EVERY child process
  - each child opens its own pool of OAP connections, sized by "Max Connections"
  - Max Connections = sum of the "Max Number of Connections" of PRIMARY servers only

Interactive usage:
  python3 webgate_tuning.py

Non-interactive usage:
  python3 webgate_tuning.py --maxclients 8000 --threadsperchild 250 \
      --serverlimit 32 --startservers 2 --minsparethreads 30 --maxsparethreads 280 \
      --webservers 5 --oam-primary 8 --oam-secondary 0 --conn-per-oam 1

Read the MPM block straight from httpd.conf:
  python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --webservers 5 --oam-primary 8
"""

import argparse
import re
import sys

# Indicative thresholds above which the number of OAP connections per Access
# Server deserves attention / load-test validation.
WARN_CONN_PER_AS = 300
CRIT_CONN_PER_AS = 800


# httpd directive -> argparse attribute. Covers legacy (2.2) and 2.4 names.
_DIRECTIVE_MAP = {
    "maxclients": "maxclients",
    "maxrequestworkers": "maxclients",
    "threadsperchild": "threadsperchild",
    "serverlimit": "serverlimit",
    "threadlimit": "threadlimit",
    "startservers": "startservers",
    "minsparethreads": "minsparethreads",
    "maxsparethreads": "maxsparethreads",
}

_MPM_BLOCK_RE = re.compile(
    r"<IfModule\s+(?:!?)?(mpm_(worker|event)_module|mpm_(worker|event)\.c)\s*>(.*?)</IfModule>",
    re.IGNORECASE | re.DOTALL,
)


def ask_int(prompt, default):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            v = int(raw)
            if v < 0:
                print("  Please enter an integer >= 0.")
                continue
            return v
        except ValueError:
            print("  Invalid value, please enter an integer.")


def parse_httpd_conf(path):
    """Extract MPM directives from an httpd.conf.

    Looks for an <IfModule mpm_worker_module|mpm_event_module> block first; if
    none is found, falls back to directives at the global level of the file.
    Commented lines (#) are ignored. Returns (directives dict, mpm_name | None).
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    def scan(chunk):
        found = {}
        for line in chunk.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"([A-Za-z]+)\s+(\d+)", line)
            if not m:
                continue
            key = m.group(1).lower()
            if key in _DIRECTIVE_MAP:
                found[_DIRECTIVE_MAP[key]] = int(m.group(2))
        return found

    blocks = _MPM_BLOCK_RE.findall(text)
    if blocks:
        # If multiple blocks exist (worker and event), merge them: the last one
        # wins, but report the name of the first MPM found.
        merged = {}
        mpm_name = None
        for b in blocks:
            body = b[3]
            name = (b[1] or b[2] or "").lower() or "worker/event"
            vals = scan(body)
            if vals and mpm_name is None:
                mpm_name = name
            merged.update(vals)
        if merged:
            return merged, mpm_name

    # Fallback: global-level directives (split configs, includes, etc.)
    return scan(text), None


def apply_conf_file(a):
    try:
        values, mpm = parse_httpd_conf(a.conf)
    except OSError as e:
        sys.exit(f"Error: cannot read '{a.conf}': {e}")
    if not values:
        sys.exit(
            f"Error: no MPM directives found in '{a.conf}'.\n"
            "Make sure the file contains an <IfModule mpm_worker_module> or "
            "<IfModule mpm_event_module> block (or global-level directives). "
            "If your config is split across files (e.g. mods-enabled/mpm_worker.conf "
            "on Debian), pass that file directly."
        )
    print(f">> Read '{a.conf}'" + (f" (MPM: {mpm})" if mpm else " (global directives, no IfModule block)"))
    for attr, val in values.items():
        # Parameters passed explicitly on the CLI take precedence over the file.
        if getattr(a, attr, None) is None:
            setattr(a, attr, val)
            print(f"   {attr:<16} = {val}")
        else:
            print(f"   {attr:<16} = {getattr(a, attr)}  (from CLI, ignoring file value {val})")
    print()
    return a


def parse_args():
    p = argparse.ArgumentParser(description="OAM WebGate tuning calculator")
    p.add_argument("--conf", type=str, metavar="HTTPD_CONF",
                   help="Path to httpd.conf: MPM directives are read from the file "
                        "(explicit CLI parameters still take precedence)")
    p.add_argument("--maxclients", type=int, help="MaxClients / MaxRequestWorkers")
    p.add_argument("--threadsperchild", type=int, help="ThreadsPerChild")
    p.add_argument("--serverlimit", type=int, help="ServerLimit")
    p.add_argument("--threadlimit", type=int, help="ThreadLimit (optional)")
    p.add_argument("--startservers", type=int, help="StartServers (default 2 if absent from the file too)")
    p.add_argument("--minsparethreads", type=int, help="MinSpareThreads (optional)")
    p.add_argument("--maxsparethreads", type=int, help="MaxSpareThreads (optional)")
    p.add_argument("--webservers", type=int, help="Number of web servers in the farm")
    p.add_argument("--oam-primary", type=int, help="Number of PRIMARY Access Servers")
    p.add_argument("--oam-secondary", type=int, default=0, help="Number of SECONDARY Access Servers (default 0)")
    p.add_argument("--conn-per-oam", type=int, default=1,
                   help="Max Number of Connections per single Access Server (default 1)")
    return p.parse_args()


def interactive_fill(a):
    print("=== Apache/OHS parameters (mpm_worker/mpm_event block) ===")
    if a.maxclients is None:
        a.maxclients = ask_int("MaxClients / MaxRequestWorkers", 8000)
    if a.threadsperchild is None:
        a.threadsperchild = ask_int("ThreadsPerChild", 250)
    if a.serverlimit is None:
        a.serverlimit = ask_int("ServerLimit", max(1, a.maxclients // a.threadsperchild))
    if a.threadlimit is None:
        a.threadlimit = ask_int("ThreadLimit", a.threadsperchild)
    if a.minsparethreads is None:
        a.minsparethreads = ask_int("MinSpareThreads", 30)
    if a.maxsparethreads is None:
        a.maxsparethreads = ask_int("MaxSpareThreads", a.minsparethreads + a.threadsperchild)
    print("\n=== Topology ===")
    if a.webservers is None:
        a.webservers = ask_int("Number of web servers (farm)", 1)
    if a.oam_primary is None:
        a.oam_primary = ask_int("PRIMARY Access Servers", 2)
    a.oam_secondary = ask_int("SECONDARY Access Servers", a.oam_secondary)
    a.conn_per_oam = ask_int("Max Number of Connections per Access Server", a.conn_per_oam)
    return a


def line(char="-", n=72):
    print(char * n)


def main():
    a = parse_args()
    if a.conf:
        a = apply_conf_file(a)
    required = (a.maxclients, a.threadsperchild, a.serverlimit, a.webservers, a.oam_primary)
    if any(v is None for v in required):
        a = interactive_fill(a)
    if a.threadlimit is None:
        a.threadlimit = a.threadsperchild
    if a.startservers is None:
        a.startservers = 2

    if a.threadsperchild <= 0 or a.maxclients <= 0:
        sys.exit("Error: MaxClients and ThreadsPerChild must be > 0.")

    # ---- Apache derivations -------------------------------------------------
    child_by_maxclients = a.maxclients // a.threadsperchild
    max_children = min(child_by_maxclients, a.serverlimit)
    effective_maxclients = max_children * a.threadsperchild

    # ---- Suggested WebGate values -------------------------------------------
    max_connections = a.conn_per_oam * a.oam_primary          # sum of PRIMARIES only
    failover_threshold = a.conn_per_oam if a.oam_secondary > 0 else 1
    aaa_timeout = 5

    # ---- Loads ---------------------------------------------------------------
    conn_per_webserver = max_connections * max_children
    conn_startup = max_connections * a.startservers
    total_farm = conn_per_webserver * a.webservers
    conn_per_as = a.conn_per_oam * max_children * a.webservers  # per primary AS

    # ---- Output ---------------------------------------------------------------
    line("=")
    print("APACHE/OHS CONFIGURATION CHECK")
    line("=")
    print(f"Max children (MaxClients/ThreadsPerChild) : {child_by_maxclients}")
    print(f"Declared ServerLimit                       : {a.serverlimit}")
    print(f"Effective children (the lower of the two)  : {max_children}")
    print(f"Effective max threads                      : {effective_maxclients}")

    warnings = []
    if a.serverlimit < child_by_maxclients:
        warnings.append(
            f"ServerLimit ({a.serverlimit}) < MaxClients/ThreadsPerChild ({child_by_maxclients}): "
            f"effective threads will stop at {effective_maxclients}, not {a.maxclients}."
        )
    if a.serverlimit > child_by_maxclients:
        warnings.append(
            f"ServerLimit ({a.serverlimit}) > required children ({child_by_maxclients}): "
            "not an error, but the scoreboard allocates shared memory for slots that will never be used."
        )
    if a.threadlimit < a.threadsperchild:
        warnings.append(
            f"ThreadLimit ({a.threadlimit}) < ThreadsPerChild ({a.threadsperchild}): "
            f"Apache will silently lower ThreadsPerChild to {a.threadlimit}."
        )
    if a.threadlimit == a.threadsperchild:
        warnings.append(
            "ThreadLimit == ThreadsPerChild: rigid configuration; raising threads in the future "
            "will require a full stop/start (ThreadLimit cannot be changed at runtime)."
        )
    if a.minsparethreads is not None and a.maxsparethreads is not None:
        floor = a.minsparethreads + a.threadsperchild
        if a.maxsparethreads < floor:
            warnings.append(
                f"MaxSpareThreads ({a.maxsparethreads}) < MinSpareThreads+ThreadsPerChild ({floor}): "
                f"Apache will correct it at runtime to {floor}."
            )

    print()
    line("=")
    print("SUGGESTED WEBGATE PROFILE")
    line("=")
    print(f"Primary Access Servers                     : {a.oam_primary}")
    print(f"Secondary Access Servers                   : {a.oam_secondary}")
    print(f"Max Number of Connections (per AS)         : {a.conn_per_oam}")
    print(f"Max Connections (sum of primaries only)    : {max_connections}")
    print(f"Failover Threshold                         : {failover_threshold}"
          + ("  (= Max Number of Connections, secondaries present)" if a.oam_secondary > 0
             else "  (default: inert without secondaries)"))
    print(f"AAA Timeout Threshold                      : {aaa_timeout} seconds  (never leave it at -1)")

    print()
    line("=")
    print("OAP CONNECTION PROJECTION")
    line("=")
    print(f"At startup (StartServers {a.startservers})               : "
          f"{conn_startup} conn. per web server")
    print(f"At full load, per single web server        : {conn_per_webserver} "
          f"({max_connections} x {max_children} children)")
    print(f"Farm total ({a.webservers} web servers)                 : {total_farm}")
    print(f"Per single primary Access Server           : {conn_per_as} "
          f"({a.conn_per_oam} x {max_children} children x {a.webservers} web servers)")

    if conn_per_as >= CRIT_CONN_PER_AS:
        warnings.append(
            f"CRITICAL: {conn_per_as} OAP connections per Access Server. Reduce Max Number of "
            "Connections (or the Apache children): concrete risk of saturating the Access Servers."
        )
    elif conn_per_as >= WARN_CONN_PER_AS:
        warnings.append(
            f"{conn_per_as} OAP connections per Access Server: high value, validate with a load test "
            "monitoring CPU/memory and TCP connections (OAP port, default 5575)."
        )

    if warnings:
        print()
        line("=")
        print("WARNINGS")
        line("=")
        for i, w in enumerate(warnings, 1):
            print(f"  {i}. {w}")

    print()
    line("=")
    print("CHECKLIST")
    line("=")
    print(f"  - Size each Access Server to handle ~{conn_per_as} OAP conn. + headroom "
          f"for reconnection bursts (child recycling / scale-up spikes).")
    print("  - Make sure every web server in the farm mounts the same WebGate profile")
    print("    and the same MPM block (otherwise re-run the script for each variant).")
    print("  - Load test: monitor `ss -tan | grep 5575` on the Access Servers during ramp-up.")
    print("  - MaxRequestsPerChild/MaxConnectionsPerChild: every child recycle recreates the")
    print("    entire OAP pool of that process; avoid values that are too low.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")

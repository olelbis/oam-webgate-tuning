# oam-webgate-tuning

A tuning calculator for **Oracle Access Manager (OAM) WebGate** running on Apache HTTP Server / Oracle HTTP Server with the **worker** or **event** MPM.

Given the MPM block of your web server and your topology (number of web servers in the farm, number of primary/secondary Access Servers), the script computes the suggested values for the WebGate profile — *Max Number of Connections*, *Max Connections*, *Failover Threshold*, *AAA Timeout Threshold* — and projects the resulting number of OAP connections landing on each Access Server, flagging inconsistencies and risky values.

```bash
python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --webservers 5 --oam-primary 8
```

If the file contains both `worker` and `event` MPM blocks, explicitly select
the MPM that is active at runtime:

```bash
python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --mpm event \
    --webservers 5 --oam-primary 8
```

No dependencies: Python 3 standard library only.

## Where the calculation comes from

The logic is based on the Oracle A-Team article **"OAM 11g Webgate Tuning"** (fusionsecurity.blogspot.com, 2016), the classic reference on WebGate sizing. The article establishes three key principles, which this script automates:

**1. The WebGate lives in child processes, not in threads.** With the worker/event MPMs, Apache consists of one parent process and N child processes, each containing `ThreadsPerChild` threads. The WebGate module is instantiated **once per child**: it is the child that opens its own pool of OAP connections to the Access Servers, and its threads *share* that pool. The connection multiplier is therefore the number of children — not the number of threads.

**2. "Max Connections" is the sum of primaries only.** In the WebGate profile, *Max Number of Connections* is set per individual Access Server; the aggregate parameter *Max Connections* must equal the sum of the *Max Number of Connections* of the **primary** servers only (secondaries are excluded from the count: they only come into play on failover).

**3. "A little goes a long way."** Since every unit of *Max Number of Connections* gets multiplied by the number of children and by the number of web servers in the farm, small values (typically 1) are almost always enough; generous values saturate the Access Servers. The article also recommends never leaving *AAA Timeout Threshold* at `-1` (which delegates to the OS TCP timeout, often 2+ minutes) but setting it to a few seconds, and — when secondaries exist — setting *Failover Threshold* equal to *Max Number of Connections*.

## How the final result is obtained, step by step

The whole calculation fits in four small steps. Follow them once with the worked example below and it will click.

### Step 0 — What we start from

Two inputs:

1. **The MPM block** of your Apache/OHS (`httpd.conf`), which tells us how big the web server can grow.
2. **The topology**: how many web servers sit in the farm, and how many OAM Access Servers they talk to.

### Step 1 — How many child processes can Apache create?

Apache serves traffic with *child processes*, each carrying `ThreadsPerChild` threads. Two directives cap the children:

- `MaxClients` (renamed `MaxRequestWorkers` in Apache 2.4) caps the **total number of threads**. Dividing it by `ThreadsPerChild` tells you how many children are needed to reach it.
- `ServerLimit` is a **hard ceiling on the number of children**, full stop.

Apache obeys whichever is lower:

```
max_children = min( MaxClients / ThreadsPerChild , ServerLimit )
```

Why we care: **each child runs its own copy of the WebGate**, and each copy opens its own connections to OAM. So `max_children` is *the* multiplier of the whole story. (If `ServerLimit` is the lower one, your real thread capacity is lower than `MaxClients` says — the script warns you about that.)

### Step 2 — Choose the per-server connection count

Pick how many OAP connections each WebGate copy should hold open **towards each single Access Server**. This is the WebGate parameter *Max Number of Connections*. Default and recommended starting point: **1**. Resist the urge to raise it — remember, it gets multiplied by `max_children` and by the farm size.

### Step 3 — Derive the WebGate profile

```
Max Connections    = conn_per_server × number_of_primaries     (primaries only!)
Failover Threshold = conn_per_server        (if secondaries exist; otherwise 1, inert)
AAA Timeout        = 5 seconds               (never -1)
```

### Step 4 — Project the load and sanity-check it

Now multiply everything out:

```
per web server (worst case) = Max Connections × max_children
farm total                  = per_web_server × number_of_web_servers
per Access Server           = conn_per_server × max_children × number_of_web_servers
```

The last number is the one that matters: it is how many OAP connections **each Access Server** must sustain when every Apache in the farm is at full load. The script warns above 300 per Access Server and flags above 800 as critical (indicative thresholds, tunable at the top of the file via `WARN_CONN_PER_AS` / `CRIT_CONN_PER_AS` — the final word always belongs to a load test).

### Worked example

Using the file in `examples/httpd.conf.sample`:

```apache
<IfModule mpm_worker_module>
        StartServers 2
        ThreadLimit 250
        ServerLimit 32
        MaxClients 8000
        MinSpareThreads 30
        MaxSpareThreads 280
        ThreadsPerChild 250
        MaxRequestsPerChild 150000
</IfModule>
```

with a farm of **5 web servers** in front of **8 Access Servers**, all primary:

| Step | Computation | Result |
|---|---|---|
| 1. Max children | min(8000 / 250, 32) | **32** |
| 2. Per-server connections | chosen default | **1** |
| 3. Max Connections | 1 × 8 primaries | **8** |
| 4a. Per web server | 8 × 32 children | **256** |
| 4b. Farm total | 256 × 5 web servers | **1280** |
| 4c. Per Access Server | 1 × 32 × 5 | **160** |

Bottom line: WebGate profile with *Max Number of Connections = 1* on each of the 8 Access Servers, *Max Connections = 8*, *AAA Timeout = 5s*; each Access Server will receive at most **160 OAP connections** from the whole farm — a healthy, perfectly symmetric load. Reproduce it with:

```bash
python3 webgate_tuning.py --conf examples/httpd.conf.sample --webservers 5 --oam-primary 8
```

## Usage

Three modes, combinable:

```bash
# 1) Interactive: prompts for everything with sensible defaults
python3 webgate_tuning.py

# 2) From httpd.conf: reads the MPM block from the file
python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --webservers 5 --oam-primary 8

# 3) Fully from the CLI (explicit parameters always win over the file)
python3 webgate_tuning.py --maxclients 8000 --threadsperchild 250 --serverlimit 32 \
    --startservers 2 --webservers 5 --oam-primary 8 --oam-secondary 0 --conn-per-oam 1
```

Main options:

| Option | Meaning |
|---|---|
| `--conf FILE` | Read MPM directives from an httpd.conf (worker or event, 2.2 and 2.4 names) |
| `--mpm worker\|event` | Required when `--conf` contains both MPM blocks; selects the active block |
| `--webservers N` | Number of web servers in the farm |
| `--oam-primary N` | Primary Access Servers |
| `--oam-secondary N` | Secondary Access Servers (activates the Failover Threshold rule) |
| `--conn-per-oam N` | Max Number of Connections per single Access Server (default 1) |

Besides the math, the script **validates the MPM block itself**: ServerLimit choking MaxClients, ThreadLimit lower than ThreadsPerChild (Apache would silently lower it), MaxSpareThreads below the `MinSpareThreads + ThreadsPerChild` floor (Apache would correct it at runtime), and the ThreadLimit == ThreadsPerChild rigidity (which prevents scaling threads without a full stop/start).

## Known limitations

The `--conf` parser does not resolve `Include` directives: if your configuration is split across files (e.g. `mods-enabled/mpm_worker.conf` on Debian/Ubuntu), pass the file containing the MPM block directly. The alert thresholds are indicative: the real capacity of an Access Server depends on hardware and managed-server tuning, so every configuration must be validated with a load test monitoring connections on the OAP port (default 5575), e.g. with `ss -tan | grep 5575`.

## References

- Oracle A-Team, *OAM 11g Webgate Tuning* — fusionsecurity.blogspot.com (2016)
- Apache HTTP Server documentation: worker/event MPM directives (`ServerLimit`, `ThreadsPerChild`, `MaxRequestWorkers`, `ThreadLimit`)
- Oracle Access Manager documentation: WebGate registration and agent profile parameters

## License

MIT — see [LICENSE](LICENSE).

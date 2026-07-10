#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webgate_tuning.py — Calcolatore di tuning per OAM WebGate su Apache/OHS (MPM worker/event)

Basato sulla logica dell'articolo A-Team "OAM 11g Webgate Tuning":
  - il modulo WebGate è istanziato da OGNI processo child
  - ogni child apre un pool di connessioni OAP pari a "Max Connections"
  - Max Connections = somma dei "Max Number of Connections" dei soli server PRIMARI

Uso interattivo:
  python3 webgate_tuning.py

Uso non interattivo:
  python3 webgate_tuning.py --maxclients 8000 --threadsperchild 250 \
      --serverlimit 32 --startservers 2 --minsparethreads 30 --maxsparethreads 280 \
      --webservers 5 --oam-primary 8 --oam-secondary 0 --conn-per-oam 1
"""

import argparse
import sys

# Soglia indicativa oltre la quale il numero di connessioni OAP per Access Server
# merita attenzione/validazione con load test.
WARN_CONN_PER_AS = 300
CRIT_CONN_PER_AS = 800


def ask_int(prompt, default):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            v = int(raw)
            if v < 0:
                print("  Inserisci un intero >= 0.")
                continue
            return v
        except ValueError:
            print("  Valore non valido, inserisci un intero.")


import re


# Direttiva httpd -> attributo argparse. Copre sia i nomi legacy (2.2) sia quelli 2.4.
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


def parse_httpd_conf(path):
    """Estrae le direttive MPM da un httpd.conf.

    Cerca prima un blocco <IfModule mpm_worker_module|mpm_event_module>; se non lo
    trova, cerca le direttive a livello globale del file. Le righe commentate (#)
    vengono ignorate. Ritorna (dict direttive, nome_mpm | None).
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
        # Se ci sono più blocchi (worker ed event), li fonde: l'ultimo vince,
        # ma segnala il nome del primo MPM trovato.
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

    # Fallback: direttive a livello globale (config splittate in più file, include, ecc.)
    return scan(text), None


def apply_conf_file(a):
    try:
        values, mpm = parse_httpd_conf(a.conf)
    except OSError as e:
        sys.exit(f"Errore: impossibile leggere '{a.conf}': {e}")
    if not values:
        sys.exit(
            f"Errore: nessuna direttiva MPM trovata in '{a.conf}'.\n"
            "Verifica che il file contenga un blocco <IfModule mpm_worker_module> o "
            "<IfModule mpm_event_module> (o le direttive a livello globale). "
            "Se la config è splittata (es. mods-enabled/mpm_worker.conf su Debian), "
            "passa direttamente quel file."
        )
    print(f">> Letto '{a.conf}'" + (f" (MPM: {mpm})" if mpm else " (direttive globali, nessun blocco IfModule)"))
    for attr, val in values.items():
        # I parametri passati esplicitamente da CLI hanno precedenza sul file.
        if getattr(a, attr, None) is None:
            setattr(a, attr, val)
            print(f"   {attr:<16} = {val}")
        else:
            print(f"   {attr:<16} = {getattr(a, attr)}  (da CLI, ignora il valore {val} del file)")
    print()
    return a


def parse_args():
    p = argparse.ArgumentParser(description="Calcolatore tuning OAM WebGate")
    p.add_argument("--conf", type=str, metavar="HTTPD_CONF",
                   help="Percorso di httpd.conf: le direttive MPM vengono lette dal file "
                        "(i parametri CLI espliciti hanno comunque precedenza)")
    p.add_argument("--maxclients", type=int, help="MaxClients / MaxRequestWorkers")
    p.add_argument("--threadsperchild", type=int, help="ThreadsPerChild")
    p.add_argument("--serverlimit", type=int, help="ServerLimit")
    p.add_argument("--threadlimit", type=int, help="ThreadLimit (opzionale)")
    p.add_argument("--startservers", type=int, help="StartServers (default 2 se assente anche dal file)")
    p.add_argument("--minsparethreads", type=int, help="MinSpareThreads (opzionale)")
    p.add_argument("--maxsparethreads", type=int, help="MaxSpareThreads (opzionale)")
    p.add_argument("--webservers", type=int, help="Numero di web server nella farm")
    p.add_argument("--oam-primary", type=int, help="Numero di Access Server PRIMARI")
    p.add_argument("--oam-secondary", type=int, default=0, help="Numero di Access Server SECONDARI (default 0)")
    p.add_argument("--conn-per-oam", type=int, default=1,
                   help="Max Number of Connections per singolo Access Server (default 1)")
    return p.parse_args()


def interactive_fill(a):
    print("=== Parametri Apache/OHS (blocco mpm_worker/mpm_event) ===")
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
    print("\n=== Topologia ===")
    if a.webservers is None:
        a.webservers = ask_int("Numero di web server (farm)", 1)
    if a.oam_primary is None:
        a.oam_primary = ask_int("Access Server PRIMARI", 2)
    a.oam_secondary = ask_int("Access Server SECONDARI", a.oam_secondary)
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
        sys.exit("Errore: MaxClients e ThreadsPerChild devono essere > 0.")

    # ---- Derivazioni Apache -------------------------------------------------
    child_by_maxclients = a.maxclients // a.threadsperchild
    max_children = min(child_by_maxclients, a.serverlimit)
    effective_maxclients = max_children * a.threadsperchild

    # ---- Valori WebGate suggeriti ------------------------------------------
    max_connections = a.conn_per_oam * a.oam_primary          # somma dei soli PRIMARI
    failover_threshold = a.conn_per_oam if a.oam_secondary > 0 else 1
    aaa_timeout = 5

    # ---- Carichi ------------------------------------------------------------
    conn_per_webserver = max_connections * max_children
    conn_startup = max_connections * a.startservers
    total_farm = conn_per_webserver * a.webservers
    conn_per_as = a.conn_per_oam * max_children * a.webservers  # per ciascun AS primario

    # ---- Output -------------------------------------------------------------
    line("=")
    print("VERIFICA CONFIGURAZIONE APACHE/OHS")
    line("=")
    print(f"Child massimi (MaxClients/ThreadsPerChild) : {child_by_maxclients}")
    print(f"ServerLimit dichiarato                     : {a.serverlimit}")
    print(f"Child effettivi (il minore dei due)        : {max_children}")
    print(f"Thread massimi effettivi                   : {effective_maxclients}")

    warnings = []
    if a.serverlimit < child_by_maxclients:
        warnings.append(
            f"ServerLimit ({a.serverlimit}) < MaxClients/ThreadsPerChild ({child_by_maxclients}): "
            f"i thread effettivi si fermeranno a {effective_maxclients}, non a {a.maxclients}."
        )
    if a.serverlimit > child_by_maxclients:
        warnings.append(
            f"ServerLimit ({a.serverlimit}) > child necessari ({child_by_maxclients}): "
            "non è un errore, ma la scoreboard alloca memoria condivisa per slot che non verranno mai usati."
        )
    if a.threadlimit < a.threadsperchild:
        warnings.append(
            f"ThreadLimit ({a.threadlimit}) < ThreadsPerChild ({a.threadsperchild}): "
            f"Apache abbasserà silenziosamente ThreadsPerChild a {a.threadlimit}."
        )
    if a.threadlimit == a.threadsperchild:
        warnings.append(
            "ThreadLimit == ThreadsPerChild: configurazione rigida; per alzare i thread in futuro "
            "servirà uno stop/start completo (ThreadLimit non è modificabile a caldo)."
        )
    if a.minsparethreads is not None and a.maxsparethreads is not None:
        floor = a.minsparethreads + a.threadsperchild
        if a.maxsparethreads < floor:
            warnings.append(
                f"MaxSpareThreads ({a.maxsparethreads}) < MinSpareThreads+ThreadsPerChild ({floor}): "
                f"Apache lo correggerà a runtime a {floor}."
            )

    print()
    line("=")
    print("PROFILO WEBGATE SUGGERITO")
    line("=")
    print(f"Access Server primari                      : {a.oam_primary}")
    print(f"Access Server secondari                    : {a.oam_secondary}")
    print(f"Max Number of Connections (per ogni AS)    : {a.conn_per_oam}")
    print(f"Max Connections (somma dei soli primari)   : {max_connections}")
    print(f"Failover Threshold                         : {failover_threshold}"
          + ("  (= Max Number of Connections, hai secondari)" if a.oam_secondary > 0
             else "  (default: inerte senza secondari)"))
    print(f"AAA Timeout Threshold                      : {aaa_timeout} secondi  (mai lasciare -1)")

    print()
    line("=")
    print("PROIEZIONE CONNESSIONI OAP")
    line("=")
    print(f"All'avvio (StartServers {a.startservers})                : "
          f"{conn_startup} conn. per web server")
    print(f"A pieno regime, per singolo web server     : {conn_per_webserver} "
          f"({max_connections} x {max_children} child)")
    print(f"Totale farm ({a.webservers} web server)                 : {total_farm}")
    print(f"Per singolo Access Server primario         : {conn_per_as} "
          f"({a.conn_per_oam} x {max_children} child x {a.webservers} web server)")

    if conn_per_as >= CRIT_CONN_PER_AS:
        warnings.append(
            f"CRITICO: {conn_per_as} connessioni OAP per Access Server. Riduci Max Number of "
            "Connections (o i child Apache): rischio concreto di saturare gli Access Server."
        )
    elif conn_per_as >= WARN_CONN_PER_AS:
        warnings.append(
            f"{conn_per_as} connessioni OAP per Access Server: valore alto, valida con load test "
            "monitorando CPU/memoria e connessioni TCP (porta OAP, default 5575)."
        )

    if warnings:
        print()
        line("=")
        print("AVVERTENZE")
        line("=")
        for i, w in enumerate(warnings, 1):
            print(f"  {i}. {w}")

    print()
    line("=")
    print("CHECKLIST")
    line("=")
    print(f"  - Dimensiona ciascun Access Server per reggere ~{conn_per_as} conn. OAP + margine "
          f"per le raffiche di riconnessione (riciclo child / picchi di scale-up).")
    print("  - Verifica che tutti i web server della farm montino lo stesso profilo WebGate")
    print("    e lo stesso blocco MPM (altrimenti rilancia lo script per ciascuna variante).")
    print("  - Load test: monitora `ss -tan | grep 5575` sugli Access Server durante la rampa.")
    print("  - MaxRequestsPerChild/MaxConnectionsPerChild: ogni riciclo child ricrea l'intero")
    print("    pool OAP di quel processo; evita valori troppo bassi.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrotto.")

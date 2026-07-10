# oam-webgate-tuning

Calcolatore di tuning per **Oracle Access Manager (OAM) WebGate** su Apache HTTP Server / Oracle HTTP Server con MPM **worker** o **event**.

Dato il blocco MPM del web server e la topologia (numero di web server in farm, numero di Access Server primari/secondari), lo script calcola i valori suggeriti per il profilo WebGate — *Max Number of Connections*, *Max Connections*, *Failover Threshold*, *AAA Timeout Threshold* — e proietta il numero di connessioni OAP risultanti su ogni Access Server, segnalando incoerenze e valori a rischio.

```bash
python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --webservers 5 --oam-primary 8
```

Nessuna dipendenza: solo Python 3 standard library.

## Origine del calcolo

La logica deriva dall'articolo dell'Oracle A-Team **"OAM 11g Webgate Tuning"** (fusionsecurity.blogspot.com, 2016), il riferimento classico sul dimensionamento dei WebGate. I principi chiave che l'articolo stabilisce, e che questo script automatizza, sono tre:

**1. Il WebGate vive nei processi child, non nei thread.** Con gli MPM worker/event, Apache è composto da un processo padre e da N processi child, ognuno dei quali contiene `ThreadsPerChild` thread. Il modulo WebGate viene istanziato **una volta per ogni child**: è il child ad aprire il proprio pool di connessioni OAP verso gli Access Server, e i suoi thread condividono quel pool. Il moltiplicatore delle connessioni è quindi il numero di child, non il numero di thread.

**2. "Max Connections" è la somma dei soli primari.** Nel profilo WebGate, il parametro *Max Number of Connections* si imposta per singolo Access Server; il parametro aggregato *Max Connections* deve essere pari alla somma dei *Max Number of Connections* dei soli server **primari** (i secondari sono esclusi dal conteggio: entrano in gioco solo in failover).

**3. "A little goes a long way."** Poiché ogni unità di *Max Number of Connections* viene moltiplicata per il numero di child e per il numero di web server della farm, valori piccoli (tipicamente 1) sono quasi sempre sufficienti; valori generosi saturano gli Access Server. L'articolo raccomanda inoltre di non lasciare mai *AAA Timeout Threshold* a `-1` (che delega al timeout TCP dell'OS, spesso oltre 2 minuti) ma di impostarlo a pochi secondi, e — in presenza di secondari — di porre *Failover Threshold* pari a *Max Number of Connections*.

## Come si ottiene il risultato finale

### Passo 1 — Child massimi del web server

Dal blocco MPM si ricava quanti processi child Apache può generare:

```
child_max = min( MaxClients / ThreadsPerChild , ServerLimit )
```

`MaxClients` (o `MaxRequestWorkers` in Apache 2.4) è il totale dei thread serventi; diviso per `ThreadsPerChild` dà i child necessari a raggiungerlo. `ServerLimit` è il tetto rigido: se è inferiore al rapporto, i thread effettivi si fermano prima (lo script lo segnala come avvertenza).

### Passo 2 — Profilo WebGate

```
Max Connections     = conn_per_oam × numero_primari
Failover Threshold  = conn_per_oam   (se esistono secondari; altrimenti 1, inerte)
AAA Timeout         = 5 secondi
```

dove `conn_per_oam` è il *Max Number of Connections* scelto per ciascun Access Server (default: **1**).

### Passo 3 — Proiezione delle connessioni OAP

```
conn_per_webserver  = Max Connections × child_max
conn_totali_farm    = conn_per_webserver × numero_webserver
conn_per_AccessServer = conn_per_oam × child_max × numero_webserver
```

L'ultimo valore è quello da confrontare con la capacità degli Access Server: lo script avvisa oltre le 300 connessioni per AS e marca come critico oltre le 800 (soglie indicative, configurabili in testa al file: `WARN_CONN_PER_AS`, `CRIT_CONN_PER_AS` — la parola finale ce l'ha sempre il load test).

### Esempio svolto

Con il file di esempio in `examples/httpd.conf.sample`:

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

e una farm di **5 web server** davanti a **8 Access Server** tutti primari:

```
child_max            = min(8000 / 250, 32)      = 32
Max Connections      = 1 × 8                     = 8
conn_per_webserver   = 8 × 32                    = 256
conn_totali_farm     = 256 × 5                   = 1280
conn_per_AS          = 1 × 32 × 5                = 160
```

Risultato: profilo WebGate con *Max Number of Connections = 1* su ciascuno degli 8 Access Server, *Max Connections = 8*, *AAA Timeout = 5s*; ogni Access Server riceverà al massimo **160 connessioni OAP** dall'intera farm — un carico sano e perfettamente simmetrico. Per riprodurlo:

```bash
python3 webgate_tuning.py --conf examples/httpd.conf.sample --webservers 5 --oam-primary 8
```

## Utilizzo

Tre modalità, combinabili:

```bash
# 1) Interattiva: chiede tutto con default sensati
python3 webgate_tuning.py

# 2) Da httpd.conf: legge il blocco MPM dal file
python3 webgate_tuning.py --conf /etc/httpd/conf/httpd.conf --webservers 5 --oam-primary 8

# 3) Tutto da CLI (i parametri espliciti vincono sempre sul file)
python3 webgate_tuning.py --maxclients 8000 --threadsperchild 250 --serverlimit 32 \
    --startservers 2 --webservers 5 --oam-primary 8 --oam-secondary 0 --conn-per-oam 1
```

Parametri principali:

| Opzione | Significato |
|---|---|
| `--conf FILE` | Legge le direttive MPM da un httpd.conf (worker o event, nomi 2.2 e 2.4) |
| `--webservers N` | Numero di web server nella farm |
| `--oam-primary N` | Access Server primari |
| `--oam-secondary N` | Access Server secondari (attiva la regola sul Failover Threshold) |
| `--conn-per-oam N` | Max Number of Connections per singolo Access Server (default 1) |

Oltre al calcolo, lo script **valida la coerenza del blocco MPM**: ServerLimit che strozza MaxClients, ThreadLimit inferiore a ThreadsPerChild (Apache lo abbasserebbe silenziosamente), MaxSpareThreads sotto il minimo `MinSpareThreads + ThreadsPerChild` (Apache lo correggerebbe a runtime), e la rigidità ThreadLimit == ThreadsPerChild (che impedisce di scalare i thread senza stop/start completo).

## Limiti noti

Il parser di `--conf` non risolve le direttive `Include`: se la configurazione è splittata su più file (es. `mods-enabled/mpm_worker.conf` su Debian/Ubuntu), passare direttamente il file che contiene il blocco MPM. Le soglie di allarme sono indicative: la capacità reale di un Access Server dipende da hardware e tuning del managed server, quindi ogni configurazione va validata con un load test monitorando le connessioni sulla porta OAP (default 5575), ad esempio con `ss -tan | grep 5575`.

## Riferimenti

- Oracle A-Team, *OAM 11g Webgate Tuning* — fusionsecurity.blogspot.com (2016)
- Documentazione Apache HTTP Server: direttive MPM worker/event (`ServerLimit`, `ThreadsPerChild`, `MaxRequestWorkers`, `ThreadLimit`)
- Documentazione Oracle Access Manager: registrazione WebGate e parametri del profilo agente

## Licenza

MIT — vedi [LICENSE](LICENSE).

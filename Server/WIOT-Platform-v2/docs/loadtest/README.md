# Load tests

`python -m wiot loadtest` starts, on spare local ports and in a temporary data folder that is deleted afterwards, the
development broker, a server subprocess with a random AES key and N encrypted virtual nodes, then polls the heaviest
dashboard calls while the fleet runs. It never touches `data/` or the field broker.

| Run | File | Published / stored | Rate | Ingest mean | API p95 (fleet / series / messages) |
|---|---|---|---|---|---|
| 12 Nov 2026, 1000 nodes × 2/min × 3 min, batch 250 ms, Windows 11, Python 3.14 | `R2.2_1000nodes.json` | 5943 / 5943 (0 % loss) | 32.6 msg/s | 20.9 ms | 285 / 82 / 89 ms |

The fleet call grows with the number of nodes in one region (1000 here); split very large fleets into regions.

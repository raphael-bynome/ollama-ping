# ollama-ping

[![Tests](https://github.com/raphael-bynome/ollama-ping/actions/workflows/tests.yml/badge.svg)](https://github.com/raphael-bynome/ollama-ping/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Dépendances](https://img.shields.io/badge/d%C3%A9pendances-aucune-brightgreen)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)

Une sonde de santé et de latence pour un serveur [Ollama](https://ollama.com), en un seul fichier
Python et sans dépendance.

Elle vérifie que le serveur répond, liste ses modèles et, si on lui donne un modèle, mesure une
génération courte : délai du premier jeton, temps de chargement du modèle, durée totale et débit. Son code de sortie permet de
s'en servir comme sonde dans un `healthcheck` Docker, un cron ou un outil de supervision.

## Installation

```bash
pipx install git+https://github.com/raphael-bynome/ollama-ping
```

## Utilisation

```console
$ ollama-ping --url http://localhost:11434 -m qwen3:8b
OK  http://localhost:11434
  version     0.12.0
  modèles     3 (llama3.2:latest, nomic-embed-text:latest, qwen3:8b)
  modèle      qwen3:8b
  1er jeton   412 ms
  chargement  95 ms
  total       980 ms
  débit       41.7 jetons/s
```

Sortie JSON pour la supervision :

```bash
ollama-ping --url http://ollama:11434 -m qwen3:8b --json
```

| Option | Rôle | Défaut |
|---|---|---|
| `--url` | adresse du serveur Ollama | `http://localhost:11434` |
| `-m`, `--model` | modèle à tester par une génération courte | aucun (pas de génération) |
| `--prompt` | prompt de la génération | `Réponds seulement : OK` |
| `--timeout` | délai maximal, en secondes | `60` |
| `--json` | sortie JSON | non |
| `--prometheus` | sortie au format d'exposition Prometheus | non |

## Codes de sortie

| Code | Sens |
|---|---|
| `0` | serveur sain (et génération réussie si `-m` est donné) |
| `1` | serveur injoignable ou génération en échec |
| `2` | modèle demandé absent du serveur |

## Exemple : contrôle périodique par cron

Toutes les 5 minutes, une génération de test, journalisée en JSON, et une ligne d'alerte dans le
journal système si la sonde échoue :

```cron
*/5 * * * * ollama-ping --url http://localhost:11434 -m qwen3:8b --json >> /var/log/ollama-ping.jsonl || logger -t ollama-ping "Ollama KO"
```

## Exemple : Prometheus et Grafana

Avec le *textfile collector* de node_exporter, une ligne de cron suffit :

```cron
*/5 * * * * ollama-ping -m qwen3:8b --prometheus > /var/lib/node_exporter/ollama.prom.tmp; mv /var/lib/node_exporter/ollama.prom.tmp /var/lib/node_exporter/ollama.prom
```

Métriques produites (étiquettes `url` et `model`) :

| Métrique | Sens |
|---|---|
| `ollama_ping_up` | 1 si le serveur (et la génération de test) répond, 0 sinon |
| `ollama_ping_models` | nombre de modèles présents |
| `ollama_ping_first_token_seconds` | délai du premier jeton |
| `ollama_ping_load_seconds` | temps de chargement du modèle |
| `ollama_ping_total_seconds` | durée totale de la génération |
| `ollama_ping_tokens_per_second` | débit |

Exemple d'alerte : `ollama_ping_up == 0` pendant 10 minutes.

## Développement

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Les tests démarrent un faux serveur Ollama local : ils ne demandent ni Ollama ni GPU.

## Licence

MIT

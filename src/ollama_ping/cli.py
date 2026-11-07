"""Vérifie qu'un serveur Ollama répond et mesure la latence d'une génération.

Codes de sortie : 0 = sain, 1 = serveur injoignable ou en erreur, 2 = modèle absent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

from . import __version__


@dataclass
class Rapport:
    url: str
    ok: bool = False
    version: str | None = None
    modeles: list[str] = field(default_factory=list)
    modele_teste: str | None = None
    premier_jeton_ms: float | None = None
    chargement_ms: float | None = None
    total_ms: float | None = None
    jetons_par_s: float | None = None
    erreur: str | None = None


def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _generer(
    base: str, modele: str, prompt: str, timeout: float
) -> tuple[float, float, float | None, float | None]:
    """Lance une génération en flux ; renvoie (premier jeton ms, total ms, jetons/s, chargement ms)."""
    corps = json.dumps({"model": modele, "prompt": prompt, "stream": True}).encode()
    req = urllib.request.Request(
        f"{base}/api/generate", data=corps, headers={"Content-Type": "application/json"}
    )
    debut = time.perf_counter()
    premier = None
    debit = None
    chargement = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for ligne in r:
            if not ligne.strip():
                continue
            morceau = json.loads(ligne)
            if premier is None and morceau.get("response"):
                premier = time.perf_counter()
            if morceau.get("done"):
                n, duree_ns = morceau.get("eval_count"), morceau.get("eval_duration")
                if n and duree_ns:
                    debit = n / (duree_ns / 1e9)
                if morceau.get("load_duration"):
                    chargement = morceau["load_duration"] / 1e6
                break
    fin = time.perf_counter()
    premier = premier or fin
    return (premier - debut) * 1000, (fin - debut) * 1000, debit, chargement


def sonder(base: str, modele: str | None, prompt: str, timeout: float) -> tuple[Rapport, int]:
    base = base.rstrip("/")
    rapport = Rapport(url=base)
    try:
        rapport.version = _get_json(f"{base}/api/version", timeout).get("version")
        tags = _get_json(f"{base}/api/tags", timeout)
        rapport.modeles = sorted(m["name"] for m in tags.get("models", []))
    except (urllib.error.URLError, OSError, ValueError) as e:
        rapport.erreur = f"serveur injoignable : {e}"
        return rapport, 1

    if modele is None:
        rapport.ok = True
        return rapport, 0

    noms = set(rapport.modeles) | {m.split(":")[0] for m in rapport.modeles if m.endswith(":latest")}
    if modele not in noms:
        rapport.erreur = f"modèle absent : {modele}"
        return rapport, 2

    rapport.modele_teste = modele
    try:
        (
            rapport.premier_jeton_ms,
            rapport.total_ms,
            rapport.jetons_par_s,
            rapport.chargement_ms,
        ) = _generer(
            base, modele, prompt, timeout
        )
    except (urllib.error.URLError, OSError, ValueError) as e:
        rapport.erreur = f"génération en échec : {e}"
        return rapport, 1
    rapport.ok = True
    return rapport, 0


def _texte(r: Rapport) -> str:
    lignes = [f"{'OK ' if r.ok else 'KO '} {r.url}"]
    if r.version:
        lignes.append(f"  version     {r.version}")
    if r.modeles:
        lignes.append(f"  modèles     {len(r.modeles)} ({', '.join(r.modeles[:5])}{'…' if len(r.modeles) > 5 else ''})")
    if r.modele_teste:
        lignes.append(f"  modèle      {r.modele_teste}")
        lignes.append(f"  1er jeton   {r.premier_jeton_ms:.0f} ms")
        if r.chargement_ms is not None:
            lignes.append(f"  chargement  {r.chargement_ms:.0f} ms")
        lignes.append(f"  total       {r.total_ms:.0f} ms")
        if r.jetons_par_s:
            lignes.append(f"  débit       {r.jetons_par_s:.1f} jetons/s")
    if r.erreur:
        lignes.append(f"  erreur      {r.erreur}")
    return "\n".join(lignes)


def _prometheus(r: Rapport) -> str:
    """Format texte d'exposition Prometheus (textfile collector de node_exporter)."""
    etiquettes = f'url="{r.url}"'
    if r.modele_teste:
        etiquettes += f',model="{r.modele_teste}"'
    metriques = [
        ("ollama_ping_up", "gauge", "1 si le serveur et la génération de test répondent", 1 if r.ok else 0),
        ("ollama_ping_models", "gauge", "nombre de modèles présents sur le serveur", len(r.modeles)),
        ("ollama_ping_first_token_seconds", "gauge", "délai du premier jeton", r.premier_jeton_ms and r.premier_jeton_ms / 1000),
        ("ollama_ping_load_seconds", "gauge", "temps de chargement du modèle", r.chargement_ms and r.chargement_ms / 1000),
        ("ollama_ping_total_seconds", "gauge", "durée totale de la génération", r.total_ms and r.total_ms / 1000),
        ("ollama_ping_tokens_per_second", "gauge", "débit de la génération", r.jetons_par_s),
    ]
    lignes = []
    for nom, genre, aide, valeur in metriques:
        if valeur is None:
            continue
        lignes += [f"# HELP {nom} {aide}", f"# TYPE {nom} {genre}", f"{nom}{{{etiquettes}}} {valeur:g}"]
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ollama-ping", description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://localhost:11434", help="adresse du serveur Ollama")
    p.add_argument("--model", "-m", help="modèle à tester par une génération courte")
    p.add_argument("--prompt", default="Réponds seulement : OK", help="prompt de la génération")
    p.add_argument("--timeout", type=float, default=60.0, help="délai maximal en secondes")
    sortie = p.add_mutually_exclusive_group()
    sortie.add_argument("--json", action="store_true", help="sortie JSON (pour la supervision)")
    sortie.add_argument("--prometheus", action="store_true", help="sortie au format Prometheus")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    rapport, code = sonder(args.url, args.model, args.prompt, args.timeout)
    if args.json:
        print(json.dumps(asdict(rapport), ensure_ascii=False))
    elif args.prometheus:
        print(_prometheus(rapport))
    else:
        print(_texte(rapport))
    return code


if __name__ == "__main__":
    sys.exit(main())

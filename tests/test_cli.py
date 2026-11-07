import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ollama_ping.cli import main, sonder


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, data):
        corps = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "0.12.0"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": "llama3.2:latest"}, {"name": "qwen3:8b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for m in ({"response": "O"}, {"response": "K"}, {"done": True, "eval_count": 2, "eval_duration": 100_000_000, "load_duration": 1_500_000_000}):
            self.wfile.write(json.dumps(m).encode() + b"\n")


@pytest.fixture
def serveur():
    httpd = HTTPServer(("127.0.0.1", 0), FauxOllama)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_serveur_sain(serveur):
    r, code = sonder(serveur, None, "x", 5)
    assert code == 0 and r.ok
    assert r.version == "0.12.0"
    assert r.modeles == ["llama3.2:latest", "qwen3:8b"]


def test_generation_mesuree(serveur):
    r, code = sonder(serveur, "qwen3:8b", "x", 5)
    assert code == 0
    assert r.total_ms >= r.premier_jeton_ms > 0
    assert r.jetons_par_s == pytest.approx(20.0)
    assert r.chargement_ms == pytest.approx(1500.0)


def test_nom_sans_latest_accepte(serveur):
    _, code = sonder(serveur, "llama3.2", "x", 5)
    assert code == 0


def test_modele_absent(serveur):
    r, code = sonder(serveur, "mistral", "x", 5)
    assert code == 2 and "absent" in r.erreur


def test_serveur_injoignable():
    r, code = sonder("http://127.0.0.1:9", None, "x", 1)
    assert code == 1 and not r.ok


def test_sortie_json(serveur, capsys):
    assert main(["--url", serveur, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_sortie_prometheus(serveur, capsys):
    assert main(["--url", serveur, "-m", "qwen3:8b", "--prometheus"]) == 0
    sortie = capsys.readouterr().out
    assert f'ollama_ping_up{{url="{serveur}",model="qwen3:8b"}} 1' in sortie
    assert "# TYPE ollama_ping_load_seconds gauge" in sortie
    assert f'ollama_ping_load_seconds{{url="{serveur}",model="qwen3:8b"}} 1.5' in sortie


def test_prometheus_serveur_injoignable(capsys):
    assert main(["--url", "http://127.0.0.1:9", "--timeout", "1", "--prometheus"]) == 1
    sortie = capsys.readouterr().out
    assert 'ollama_ping_up{url="http://127.0.0.1:9"} 0' in sortie
    assert "first_token" not in sortie

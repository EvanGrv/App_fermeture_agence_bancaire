import json
import subprocess
import sys
import threading
import time
import uuid
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

from backend.env import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
_RUN_LOCK = threading.Lock()
_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _new_job(since: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "since": since,
            "ok": True,
            "state": "queued",
            "progress": 0,
            "step": "En attente",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "started_at": time.time(),
            "finished_at": None,
        }
    return job_id


def _update_job(job_id: str, **updates) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(updates)


def _append_job(job_id: str, field: str, text: str) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id][field] = (_JOBS[job_id].get(field) or "") + text


def _snapshot(job_id: str):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _jobs_summary():
    with _JOBS_LOCK:
        return [
            {
                "id": job["id"],
                "since": job["since"],
                "ok": job["ok"],
                "state": job["state"],
                "progress": job["progress"],
                "step": job["step"],
                "returncode": job["returncode"],
                "started_at": job["started_at"],
                "finished_at": job["finished_at"],
                "proc_pid": job.get("proc_pid"),
            }
            for job in sorted(_JOBS.values(), key=lambda item: item["started_at"], reverse=True)
        ]


def _has_active_job():
    with _JOBS_LOCK:
        return any(job.get("state") in {"queued", "running"} for job in _JOBS.values())


def _run_pipeline_job(job_id: str, since: str) -> None:
    if not _RUN_LOCK.acquire(blocking=False):
        _update_job(job_id, ok=False, state="error", step="Un pipeline est déjà en cours", finished_at=time.time())
        return
    _update_job(job_id, state="running", progress=3, step="Démarrage du processus Python")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "run.py", "--since", since],
            cwd=str(ROOT),
            env=load_dotenv(ROOT / ".env", env=os.environ.copy()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        _update_job(job_id, proc_pid=proc.pid)
        assert proc.stdout is not None
        assert proc.stderr is not None

        def read_stderr():
            for line in proc.stderr:
                _append_job(job_id, "stderr", line)

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        for line in proc.stdout:
            _append_job(job_id, "stdout", line)
            if line.startswith("[progress]"):
                parts = line.strip().split(" ", 2)
                if len(parts) == 3 and parts[1].isdigit():
                    _update_job(job_id, progress=int(parts[1]), step=parts[2])

        returncode = proc.wait(timeout=60 * 60 * 3)
        stderr_thread.join(timeout=1)
        if returncode == 0:
            _update_job(job_id, ok=True, state="done", progress=100, step="Terminé", returncode=returncode, finished_at=time.time(), proc_pid=None)
        else:
            _update_job(job_id, ok=False, state="error", step="Le pipeline a échoué", returncode=returncode, finished_at=time.time(), proc_pid=None)
    except subprocess.TimeoutExpired:
        _update_job(job_id, ok=False, state="error", step="Le pipeline a dépassé le délai maximal", finished_at=time.time(), proc_pid=None)
    except Exception as exc:
        _append_job(job_id, "stderr", f"{exc}\n")
        _update_job(job_id, ok=False, state="error", step="Erreur serveur pendant le pipeline", finished_at=time.time(), proc_pid=None)
    finally:
        if _RUN_LOCK.locked():
            _RUN_LOCK.release()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/pipeline/jobs":
            self._json({"ok": True, "jobs": _jobs_summary(), "locked": _RUN_LOCK.locked()})
            return
        if self.path.startswith("/api/pipeline/status/"):
            job_id = self.path.rsplit("/", 1)[-1]
            job = _snapshot(job_id)
            if not job:
                self._json({"ok": False, "error": "Job introuvable."}, status=404)
                return
            self._json(job)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/pipeline/run":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "JSON invalide."}, status=400)
            return
        since = str(payload.get("since") or "").strip()
        if not since:
            self._json({"ok": False, "error": "Le champ since est obligatoire."}, status=400)
            return
        try:
            date.fromisoformat(since)
        except ValueError:
            self._json({"ok": False, "error": "La date doit être au format YYYY-MM-DD."}, status=400)
            return
        if _RUN_LOCK.locked() and not _has_active_job():
            _RUN_LOCK.release()
        if _RUN_LOCK.locked():
            self._json({"ok": False, "error": "Un pipeline est déjà en cours."}, status=409)
            return
        job_id = _new_job(since)
        thread = threading.Thread(target=_run_pipeline_job, args=(job_id, since), daemon=True)
        thread.start()
        self._json({"ok": True, "job_id": job_id, "state": "queued", "progress": 0, "step": "En attente"})

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"App disponible sur http://127.0.0.1:{port}/frontend/index.html")
    print("API pipeline: POST /api/pipeline/run, GET /api/pipeline/status/<job_id>")
    server.serve_forever()


if __name__ == "__main__":
    main()

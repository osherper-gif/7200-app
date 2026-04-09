"""
MDS — Multi-Disciplinary System Server  (Tornado edition)
Shared data storage, user locking, heartbeat — no external dependencies needed.

Usage:
    python server.py [--port 5000] [--data-dir ./data]
"""

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ai_actions import (
    analyze_architecture,
    analyze_requirement,
    analyze_review_readiness,
    analyze_risk,
)
from offline_ai_service import ask_offline_ai

# ── Tornado import (stdlib fallback: http.server) ─────────────
try:
    import tornado.ioloop
    import tornado.web
    import tornado.httpserver
    HAS_TORNADO = True
except ImportError:
    HAS_TORNADO = False

# ── Config ────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--port",     type=int, default=5000)
parser.add_argument("--data-dir", type=str, default="./data")
args, _ = parser.parse_known_args()

PORT      = args.port
DATA_DIR  = Path(args.data_dir)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "project_data.json"
LOCK_FILE = DATA_DIR / "project_lock.json"
LOG_FILE  = DATA_DIR / "activity_log.txt"
LOCK_TIMEOUT_MINUTES = 30

_lock = threading.Lock()   # filesystem mutex

# ── Persistence helpers ───────────────────────────────────────
def now_str():
    return datetime.now().isoformat(timespec="seconds")

def log(msg):
    line = f"[{now_str()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def read_json(path, default=None):
    try:
        if Path(path).exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {} if default is None else default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_lock():
    ld = read_json(LOCK_FILE, {"locked": False})
    # Auto-expire
    if ld.get("locked"):
        hb = ld.get("last_heartbeat")
        if not hb:
            ld = {"locked": False}
        else:
            try:
                last = datetime.fromisoformat(hb)
                if datetime.now() - last > timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                    log(f"AUTO-EXPIRE lock by {ld.get('user','?')}")
                    ld = {"locked": False}
            except Exception:
                ld = {"locked": False}
        if not ld.get("locked"):
            write_json(LOCK_FILE, ld)
    return ld


def run_ai_action(action_type, body):
    project_context = body.get("project_context") or {}
    user_input = (body.get("input") or body.get("text") or "").strip()
    if action_type == "requirements":
        result = analyze_requirement(project_context, user_input)
    elif action_type == "risks":
        result = analyze_risk(project_context, user_input)
    elif action_type == "architecture":
        result = analyze_architecture(project_context, user_input)
    elif action_type == "review-readiness":
        result = analyze_review_readiness(project_context)
    else:
        raise ValueError(f"Unsupported AI action: {action_type}")
    debug = result.pop("_debug", {})
    log(
        "AI_ACTION_DEBUG_V1 action_type={action_type} input_size={input_size} output_size={output_size} project_items_used={project_items_used}".format(
            action_type=debug.get("action_type", action_type),
            input_size=debug.get("input_size", 0),
            output_size=debug.get("output_size", 0),
            project_items_used=debug.get("project_items_used", 0),
        )
    )
    return result

# ── CORS / JSON base handler ──────────────────────────────────
if HAS_TORNADO:
    class BaseHandler(tornado.web.RequestHandler):
        def set_default_headers(self):
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
            self.set_header("Access-Control-Allow-Headers",
                            "Content-Type,X-Username")
            self.set_header("Content-Type", "application/json; charset=utf-8")

        def options(self, *args, **kwargs):
            self.set_status(204)
            self.finish()

        def json_body(self):
            try:
                return json.loads(self.request.body or b"{}")
            except Exception:
                return {}

        def send(self, data, status=200):
            self.set_status(status)
            self.write(json.dumps(data, ensure_ascii=False))

        def user(self):
            return (self.request.headers.get("X-Username") or "").strip() or "Unknown"

    # ── /api/status ──────────────────────────────────────────────
    class StatusHandler(BaseHandler):
        def get(self):
            with _lock:
                ld = get_lock()
            self.send({"status": "ok", "version": "2.0",
                       "server_time": now_str(), "lock": ld})

    # ── /api/data ─────────────────────────────────────────────────
    class DataHandler(BaseHandler):
        def get(self):
            with _lock:
                data = read_json(DATA_FILE)
            self.send(data)

        def post(self):
            u = self.user()
            with _lock:
                ld = get_lock()
                if ld.get("locked") and ld.get("user") != u:
                    self.send({"ok": False, "error": "locked",
                               "user": ld["user"],
                               "message": f"המסמך נעול על ידי {ld['user']}"}, 403)
                    return
                payload = self.json_body()
                write_json(DATA_FILE, payload)
                log(f"SAVE  user={u}  keys={len(payload)}")
            self.send({"ok": True, "saved_at": now_str()})

    # ── /api/lock ─────────────────────────────────────────────────
    class LockHandler(BaseHandler):
        def get(self):
            with _lock:
                ld = get_lock()
            self.send(ld)

        def post(self):
            u = self.json_body().get("user") or self.user()
            if not u or u == "Unknown":
                self.send({"ok": False, "error": "no_user"}, 400)
                return
            with _lock:
                ld = get_lock()
                if ld.get("locked") and ld.get("user") != u:
                    self.send({"ok": False, "error": "locked",
                               "user": ld["user"],
                               "acquired_at": ld.get("acquired_at"),
                               "last_heartbeat": ld.get("last_heartbeat")}, 409)
                    return
                t = now_str()
                new_ld = {
                    "locked": True,
                    "user": u,
                    "acquired_at": ld.get("acquired_at", t) if ld.get("user") == u else t,
                    "last_heartbeat": t
                }
                write_json(LOCK_FILE, new_ld)
                log(f"LOCK  user={u}")
            self.send({"ok": True, "lock": new_ld})

        def delete(self):
            u = self.user()
            force = self.get_argument("force", "0") == "1"
            with _lock:
                ld = get_lock()
                if ld.get("locked"):
                    if ld.get("user") == u or force:
                        write_json(LOCK_FILE, {"locked": False})
                        log(f"UNLOCK user={u} force={force}")
                    else:
                        self.send({"ok": False, "error": "not_owner",
                                   "owner": ld.get("user")}, 403)
                        return
            self.send({"ok": True})

    # ── /api/heartbeat ────────────────────────────────────────────
    class HeartbeatHandler(BaseHandler):
        def post(self):
            u = self.user()
            with _lock:
                ld = read_json(LOCK_FILE, {"locked": False})
                if ld.get("locked") and ld.get("user") == u:
                    ld["last_heartbeat"] = now_str()
                    write_json(LOCK_FILE, ld)
            self.send({"ok": True, "ts": now_str()})

    # ── /api/log ──────────────────────────────────────────────────
    class LogHandler(BaseHandler):
        def get(self):
            try:
                lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
                self.send({"lines": lines[-100:]})
            except Exception:
                self.send({"lines": []})

    class OfflineAIAskHandler(BaseHandler):
        def post(self):
            try:
                body = self.json_body()
                question = (body.get("question") or "").strip()
                project_context = body.get("project_context") or {}
                result = ask_offline_ai(question, project_context)
                debug = result.pop("_debug", {})
                log(
                    "OFFLINE_AI_DEBUG_V4 question={q} used_items={items} confidence={confidence} refusal={refusal} contradiction={contradiction} critical={critical} path={path} question_type={question_type} project_context_used={project_context_used} project_evidence_count={project_evidence_count} kb_evidence_count={kb_evidence_count} decision_source={decision_source} intent_type={intent_type} intent_subtype={intent_subtype} is_multi={is_multi} sub_question_count={sub_question_count}".format(
                        q=question,
                        items=",".join(result.get("used_items") or []),
                        confidence=result.get("confidence"),
                        refusal=result.get("refusal"),
                        contradiction=debug.get("contradiction"),
                        critical=debug.get("is_critical_fact_question"),
                        path=debug.get("decision_path"),
                        question_type=debug.get("question_type"),
                        project_context_used=debug.get("project_context_used"),
                        project_evidence_count=debug.get("project_evidence_count"),
                        kb_evidence_count=debug.get("kb_evidence_count"),
                        decision_source=debug.get("decision_source"),
                        intent_type=debug.get("intent_type"),
                        intent_subtype=debug.get("intent_subtype"),
                        is_multi=debug.get("is_multi"),
                        sub_question_count=debug.get("sub_question_count"),
                    )
                )
                self.send(result)
            except Exception as ex:
                log(f"OFFLINE_AI_ERROR {ex}")
                self.send(
                    {
                        "answer": "אין לי מספיק מידע מקומי כדי לקבוע.\nלמה: אירעה שגיאה פנימית בעיבוד השאלה.\nצעד מעשי הבא: לנסות שוב או לבדוק את קבצי הידע המקומיים.",
                        "confidence": "low",
                        "used_items": [],
                        "missing_information": ["אירעה שגיאה פנימית בעיבוד השאלה"],
                        "recommended_action": "לנסות שוב או לבדוק את קבצי הידע המקומיים.",
                        "refusal": True,
                    },
                    500,
                )

    class AIRequirementsHandler(BaseHandler):
        def post(self):
            try:
                self.send(run_ai_action("requirements", self.json_body()))
            except Exception as ex:
                log(f"AI_ACTION_ERROR requirements {ex}")
                self.send({"error": "ai_action_failed", "message": str(ex)}, 500)

    class AIRisksHandler(BaseHandler):
        def post(self):
            try:
                self.send(run_ai_action("risks", self.json_body()))
            except Exception as ex:
                log(f"AI_ACTION_ERROR risks {ex}")
                self.send({"error": "ai_action_failed", "message": str(ex)}, 500)

    class AIArchitectureHandler(BaseHandler):
        def post(self):
            try:
                self.send(run_ai_action("architecture", self.json_body()))
            except Exception as ex:
                log(f"AI_ACTION_ERROR architecture {ex}")
                self.send({"error": "ai_action_failed", "message": str(ex)}, 500)

    class AIReviewReadinessHandler(BaseHandler):
        def post(self):
            try:
                self.send(run_ai_action("review-readiness", self.json_body()))
            except Exception as ex:
                log(f"AI_ACTION_ERROR review-readiness {ex}")
                self.send({"error": "ai_action_failed", "message": str(ex)}, 500)

    # ── /api/patch — apply code fix to 7200_System_v2.html ───────
    class PatchHandler(BaseHandler):
        def post(self):
            import re as _re
            try:
                body = json.loads(self.request.body.decode("utf-8"))
                target  = body.get("file", "7200_System_v2.html")
                patches = body.get("patches", [])   # [{old, new}]
                dry_run = body.get("dry_run", False)
                app_file = Path(__file__).parent / target
                if not app_file.exists():
                    self.send({"ok":False,"error":f"{target} not found"}); return
                src = app_file.read_text(encoding="utf-8")
                applied, skipped = [], []
                for p in patches:
                    old, new = p.get("old",""), p.get("new","")
                    if old and old in src:
                        src = src.replace(old, new, 1)
                        applied.append(p.get("id","patch"))
                    else:
                        skipped.append(p.get("id","patch"))
                if not dry_run and applied:
                    app_file.write_text(src, encoding="utf-8")
                    log(f"PATCH applied={applied} skipped={skipped}")
                self.send({"ok":True,"applied":applied,"skipped":skipped,
                           "total":len(patches),"dry_run":dry_run})
            except Exception as ex:
                self.send({"ok":False,"error":str(ex)}, 500)

        def options(self):
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "POST,OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type")
            self.set_status(204); self.finish()

    # ── Static files ──────────────────────────────────────────────
    class StaticHtmlHandler(tornado.web.StaticFileHandler):
        def set_default_headers(self):
            self.set_header("Access-Control-Allow-Origin", "*")

    def make_app():
        return tornado.web.Application([
            (r"/api/status",    StatusHandler),
            (r"/api/data",      DataHandler),
            (r"/api/lock",      LockHandler),
            (r"/api/heartbeat", HeartbeatHandler),
            (r"/api/log",       LogHandler),
            (r"/api/offline-ai/ask", OfflineAIAskHandler),
            (r"/api/ai/requirements", AIRequirementsHandler),
            (r"/api/ai/risks", AIRisksHandler),
            (r"/api/ai/architecture", AIArchitectureHandler),
            (r"/api/ai/review-readiness", AIReviewReadinessHandler),
            (r"/api/patch",     PatchHandler),
            (r"/(.*)",          StaticHtmlHandler,
             {"path": str(Path(__file__).parent), "default_filename": "7200_System_v2.html"}),
        ])


# ─────────────────────────────────────────────────────────────
# Fallback: stdlib http.server (no external deps at all)
# ─────────────────────────────────────────────────────────────
else:
    import http.server
    import urllib.parse

    class MdsHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # silence default access log

        def cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Username")

        def user(self):
            return (self.headers.get("X-Username") or "").strip() or "Unknown"

        def body_json(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def send_json(self, data, code=200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path, mime):
            try:
                body = open(path, "rb").read()
                self.send_response(200)
                self.cors()
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404)

        def do_OPTIONS(self):
            self.send_response(204); self.cors(); self.end_headers()

        def route(self, method):
            p = urllib.parse.urlparse(self.path).path
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            u = self.user()

            if p == "/api/status" and method == "GET":
                with _lock:
                    ld = get_lock()
                self.send_json({"status":"ok","version":"2.0","server_time":now_str(),"lock":ld})

            elif p == "/api/data" and method == "GET":
                with _lock:
                    d = read_json(DATA_FILE)
                self.send_json(d)

            elif p == "/api/data" and method == "POST":
                with _lock:
                    ld = get_lock()
                    if ld.get("locked") and ld.get("user") != u:
                        self.send_json({"ok":False,"error":"locked","user":ld["user"]},403); return
                    write_json(DATA_FILE, self.body_json())
                    log(f"SAVE user={u}")
                self.send_json({"ok":True,"saved_at":now_str()})

            elif p == "/api/lock" and method == "GET":
                with _lock:
                    self.send_json(get_lock())

            elif p == "/api/lock" and method == "POST":
                body = self.body_json(); user2 = body.get("user", u)
                with _lock:
                    ld = get_lock()
                    if ld.get("locked") and ld.get("user") != user2:
                        self.send_json({"ok":False,"error":"locked","user":ld["user"]},409); return
                    t = now_str()
                    ld2 = {"locked":True,"user":user2,
                           "acquired_at": ld.get("acquired_at",t) if ld.get("user")==user2 else t,
                           "last_heartbeat":t}
                    write_json(LOCK_FILE, ld2)
                    log(f"LOCK user={user2}")
                self.send_json({"ok":True,"lock":ld2})

            elif p == "/api/lock" and method == "DELETE":
                force = q.get("force",["0"])[0] == "1"
                with _lock:
                    ld = get_lock()
                    if ld.get("locked") and (ld.get("user")==u or force):
                        write_json(LOCK_FILE,{"locked":False}); log(f"UNLOCK user={u}")
                    elif ld.get("locked"):
                        self.send_json({"ok":False,"error":"not_owner","owner":ld.get("user")},403); return
                self.send_json({"ok":True})

            elif p == "/api/heartbeat" and method == "POST":
                with _lock:
                    ld = read_json(LOCK_FILE,{"locked":False})
                    if ld.get("locked") and ld.get("user")==u:
                        ld["last_heartbeat"]=now_str(); write_json(LOCK_FILE,ld)
                self.send_json({"ok":True,"ts":now_str()})

            elif p == "/api/offline-ai/ask" and method == "POST":
                try:
                    body = self.body_json()
                    question = (body.get("question") or "").strip()
                    project_context = body.get("project_context") or {}
                    result = ask_offline_ai(question, project_context)
                    debug = result.pop("_debug", {})
                    log(
                        "OFFLINE_AI_DEBUG_V4 question={q} used_items={items} confidence={confidence} refusal={refusal} contradiction={contradiction} critical={critical} path={path} question_type={question_type} project_context_used={project_context_used} project_evidence_count={project_evidence_count} kb_evidence_count={kb_evidence_count} decision_source={decision_source} intent_type={intent_type} intent_subtype={intent_subtype} is_multi={is_multi} sub_question_count={sub_question_count}".format(
                            q=question,
                            items=",".join(result.get("used_items") or []),
                            confidence=result.get("confidence"),
                            refusal=result.get("refusal"),
                            contradiction=debug.get("contradiction"),
                            critical=debug.get("is_critical_fact_question"),
                            path=debug.get("decision_path"),
                            question_type=debug.get("question_type"),
                            project_context_used=debug.get("project_context_used"),
                            project_evidence_count=debug.get("project_evidence_count"),
                            kb_evidence_count=debug.get("kb_evidence_count"),
                            decision_source=debug.get("decision_source"),
                            intent_type=debug.get("intent_type"),
                            intent_subtype=debug.get("intent_subtype"),
                            is_multi=debug.get("is_multi"),
                            sub_question_count=debug.get("sub_question_count"),
                        )
                    )
                    self.send_json(result)
                except Exception as ex:
                    log(f"OFFLINE_AI_ERROR {ex}")
                    self.send_json(
                        {
                            "answer": "אין לי מספיק מידע מקומי כדי לקבוע.\nלמה: אירעה שגיאה פנימית בעיבוד השאלה.\nצעד מעשי הבא: לנסות שוב או לבדוק את קבצי הידע המקומיים.",
                            "confidence": "low",
                            "used_items": [],
                            "missing_information": ["אירעה שגיאה פנימית בעיבוד השאלה"],
                            "recommended_action": "לנסות שוב או לבדוק את קבצי הידע המקומיים.",
                            "refusal": True,
                        },
                        500,
                    )

            elif p == "/api/ai/requirements" and method == "POST":
                try:
                    self.send_json(run_ai_action("requirements", self.body_json()))
                except Exception as ex:
                    log(f"AI_ACTION_ERROR requirements {ex}")
                    self.send_json({"error": "ai_action_failed", "message": str(ex)}, 500)

            elif p == "/api/ai/risks" and method == "POST":
                try:
                    self.send_json(run_ai_action("risks", self.body_json()))
                except Exception as ex:
                    log(f"AI_ACTION_ERROR risks {ex}")
                    self.send_json({"error": "ai_action_failed", "message": str(ex)}, 500)

            elif p == "/api/ai/architecture" and method == "POST":
                try:
                    self.send_json(run_ai_action("architecture", self.body_json()))
                except Exception as ex:
                    log(f"AI_ACTION_ERROR architecture {ex}")
                    self.send_json({"error": "ai_action_failed", "message": str(ex)}, 500)

            elif p == "/api/ai/review-readiness" and method == "POST":
                try:
                    self.send_json(run_ai_action("review-readiness", self.body_json()))
                except Exception as ex:
                    log(f"AI_ACTION_ERROR review-readiness {ex}")
                    self.send_json({"error": "ai_action_failed", "message": str(ex)}, 500)

            elif p == "/api/patch" and method == "POST":
                try:
                    body = self.body_json()
                    target  = body.get("file", "7200_System_v2.html")
                    patches = body.get("patches", [])
                    dry_run = body.get("dry_run", False)
                    app_file = Path(__file__).parent / target
                    if not app_file.exists():
                        self.send_json({"ok": False, "error": f"{target} not found"}); return
                    src = app_file.read_text(encoding="utf-8")
                    applied, skipped = [], []
                    for pp in patches:
                        old_s, new_s = pp.get("old", ""), pp.get("new", "")
                        if old_s and old_s in src:
                            src = src.replace(old_s, new_s, 1)
                            applied.append(pp.get("id", "patch"))
                        else:
                            skipped.append(pp.get("id", "patch"))
                    if not dry_run and applied:
                        app_file.write_text(src, encoding="utf-8")
                        log(f"PATCH applied={applied} skipped={skipped}")
                    self.send_json({"ok": True, "applied": applied, "skipped": skipped, "dry_run": dry_run})
                except Exception as ex:
                    self.send_json({"ok": False, "error": str(ex)}, 500)

            elif p in ("/", "/index.html", "/7200_System_v2.html"):
                self.send_file(str(Path(__file__).parent / "7200_System_v2.html"),
                               "text/html; charset=utf-8")
            else:
                fpath = Path(__file__).parent / p.lstrip("/")
                if fpath.exists() and fpath.is_file():
                    mime = "text/html" if fpath.suffix == ".html" else "application/octet-stream"
                    self.send_file(str(fpath), mime)
                else:
                    self.send_error(404)

        def do_GET(self):    self.route("GET")
        def do_POST(self):   self.route("POST")
        def do_DELETE(self): self.route("DELETE")


# ── Main ──────────────────────────────────────────────────────
def main():
    banner = f"""
╔══════════════════════════════════════════════════════╗
║  MDS Project System — Server v2.0                    ║
║  Engine   : {'Tornado' if HAS_TORNADO else 'stdlib http.server':<43}║
║  Data dir : {str(DATA_DIR):<43}║
║  Timeout  : {LOCK_TIMEOUT_MINUTES} min inactivity                         ║
╠══════════════════════════════════════════════════════╣
║  Open in browser:  http://localhost:{PORT:<17}║
║  Network access:   http://<YOUR-IP>:{PORT:<17}║
╚══════════════════════════════════════════════════════╝
"""
    print(banner)

    if HAS_TORNADO:
        app = make_app()
        app.listen(PORT, address="0.0.0.0")
        print(f"Tornado listening on port {PORT} ...")
        tornado.ioloop.IOLoop.current().start()
    else:
        server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), MdsHandler)
        print(f"stdlib HTTPServer listening on port {PORT} ...")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
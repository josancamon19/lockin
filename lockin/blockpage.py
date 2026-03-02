"""Local HTTP server that serves a branded block page for blocked domains."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SESSION_FILE = Path("/var/lockin/session.json")

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Locked In</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0a0a0a;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }
  .card {
    background: #1a1a1a;
    border: 1px solid #333;
    border-radius: 16px;
    padding: 48px 56px;
    text-align: center;
    max-width: 480px;
    width: 90%;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  }
  .icon { font-size: 64px; margin-bottom: 16px; }
  h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; color: #fff; }
  .profile { font-size: 14px; color: #888; margin-bottom: 24px; }
  .countdown {
    font-size: 48px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: #ff6b35;
    margin-bottom: 24px;
    letter-spacing: 2px;
  }
  .message { font-size: 15px; color: #999; line-height: 1.5; }
  .no-session { color: #666; font-size: 16px; margin-top: 16px; }
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x1F512;</div>
  <h1>Locked In</h1>
  <div class="profile" id="profile"></div>
  <div class="countdown" id="countdown">--:--:--</div>
  <div class="message" id="message">Stay focused. You got this.</div>
</div>
<script>
(function() {
  var endTime = null;
  var profileName = null;

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function updateDisplay() {
    var el = document.getElementById('countdown');
    var msg = document.getElementById('message');
    var prof = document.getElementById('profile');

    if (!endTime) {
      el.textContent = '--:--:--';
      msg.textContent = 'No active focus session.';
      msg.className = 'message no-session';
      prof.textContent = '';
      return;
    }

    var now = Date.now() / 1000;
    var remaining = Math.max(0, endTime - now);

    if (remaining <= 0) {
      el.textContent = '00:00:00';
      msg.textContent = 'Session complete! Refreshing...';
      setTimeout(function() { location.reload(); }, 3000);
      return;
    }

    var h = Math.floor(remaining / 3600);
    var m = Math.floor((remaining % 3600) / 60);
    var s = Math.floor(remaining % 60);
    el.textContent = pad(h) + ':' + pad(m) + ':' + pad(s);
    prof.textContent = profileName ? 'Profile: ' + profileName : '';
    msg.textContent = 'Stay focused. You got this.';
    msg.className = 'message';
  }

  function fetchSession() {
    fetch('/api/session')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        endTime = data.end_time || null;
        profileName = data.profile_name || null;
        updateDisplay();
      })
      .catch(function() {
        endTime = null;
        profileName = null;
        updateDisplay();
      });
  }

  fetchSession();
  setInterval(updateDisplay, 1000);
  setInterval(fetchSession, 10000);
})();
</script>
</body>
</html>
"""


def _read_session() -> dict:
    """Read the session file for display data (no HMAC validation needed)."""
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text())
            return {
                "profile_name": data.get("profile_name"),
                "end_time": data.get("end_time"),
            }
    except (json.JSONDecodeError, OSError):
        pass
    return {"profile_name": None, "end_time": None}


class _BlockPageHandler(BaseHTTPRequestHandler):
    """Serves the block page HTML on any path, JSON at /api/session."""

    def do_GET(self) -> None:
        if self.path == "/api/session":
            data = _read_session()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            body = _HTML_TEMPLATE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress access logs."""
        pass


_server: HTTPServer | None = None


def start_block_page_server(port: int = 80) -> None:
    """Start the block page HTTP server as a daemon thread."""
    global _server
    if _server is not None:
        return
    try:
        _server = HTTPServer(("127.0.0.1", port), _BlockPageHandler)
        thread = threading.Thread(target=_server.serve_forever, daemon=True)
        thread.start()
    except OSError:
        # Port 80 may already be in use — non-fatal
        _server = None


def stop_block_page_server() -> None:
    """Shut down the block page HTTP server."""
    global _server
    if _server is not None:
        _server.shutdown()
        _server = None

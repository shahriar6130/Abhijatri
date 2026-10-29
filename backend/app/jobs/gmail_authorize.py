"""One-time Gmail authorisation for EMAIL_PROVIDER=gmail: prints a refresh token.

    python -m app.jobs.gmail_authorize --client-id <id> --client-secret <secret>

Run it in your own terminal (not through a chat tool): it opens Google's consent page for the
``gmail.send`` scope only, waits on a localhost port for Google's redirect, and prints the refresh
token once. Paste that token into ``GMAIL_REFRESH_TOKEN`` yourself (backend/.env and Railway).
The OAuth client must be of type "Desktop app" in Google Cloud.
"""

import argparse
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

SCOPE = "https://www.googleapis.com/auth/gmail.send"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret


def main() -> None:
    parser = argparse.ArgumentParser(description="Get a Gmail API refresh token (scope gmail.send).")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    arguments = parser.parse_args()

    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            ok = query.get("state") == state and "code" in query
            if ok:
                result["code"] = query["code"]
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal." if ok else b"Authorisation failed.")

        def log_message(self, *_: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": arguments.client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
    })
    print("Opening Google's consent page. If it does not open, paste this address into the browser:\n" + url)
    webbrowser.open(url)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    thread.join(timeout=300)
    server.server_close()
    if "code" not in result:
        print("No authorisation received within 5 minutes.", file=sys.stderr)
        sys.exit(1)
    response = httpx.post(TOKEN_URL, data={
        "code": result["code"], "client_id": arguments.client_id, "client_secret": arguments.client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    }, timeout=20)
    token = response.json().get("refresh_token") if response.status_code == 200 else None
    if not token:
        print(f"Google did not return a refresh token ({response.status_code}).", file=sys.stderr)
        sys.exit(2)
    print("\nGMAIL_REFRESH_TOKEN=" + token)
    print("\nPut that line, GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET into backend/.env (and Railway), with EMAIL_PROVIDER=gmail.")


if __name__ == "__main__":
    main()

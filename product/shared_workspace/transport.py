"""Authenticated local/HTTPS transport for the authoritative engine.

Serving is optional and requires Uvicorn. Local-only operation uses no server or
third-party package. Transport never redirects bearer credentials to another URL.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .errors import ProductError

MAX_BODY = 128 * 1024 * 1024


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def read_token(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ProductError(5, "credential_missing", "A regular private token file is required.")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ProductError(5, "credential_permissions", "Token file must be readable only by its owner (mode 0600).")
    token = path.read_text(encoding="utf-8").strip()
    if not 32 <= len(token) <= 512 or any(c.isspace() for c in token):
        raise ProductError(3, "credential_invalid", "Invalid credential file format.")
    return token


class LocalTransport:
    def __init__(self, db_path, token_file):
        self.db_path, self.token_file = Path(db_path), Path(token_file)

    def __call__(self, operation, payload):
        from .engine import Coordinator
        return Coordinator(self.db_path).request(read_token(self.token_file), operation, payload)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def __init__(self, endpoint, token_file, ca_file=None, timeout=30):
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in {"", "/"}):
            raise ProductError(3, "endpoint_invalid", "Use an HTTPS coordinator origin without credentials, path or query.")
        if parsed.scheme == "http" and not loopback(parsed.hostname):
            raise ProductError(3, "tls_required", "Non-loopback coordinator connections require verified HTTPS.")
        self.endpoint = endpoint.rstrip("/") + "/v1/request"
        self.token_file = token_file
        self.timeout = timeout
        # Explicitly disable environment proxies: credentials go only to the
        # selected coordinator. HTTPS certificate and hostname checks stay on.
        context = ssl.create_default_context(cafile=ca_file) if parsed.scheme == "https" else None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context))

    def __call__(self, operation, payload):
        body = json.dumps({"protocol": 1, "operation": operation, "payload": payload}, ensure_ascii=False).encode()
        if len(body) > MAX_BODY:
            raise ProductError(3, "payload_too_large", "Request exceeds the 128 MiB transport limit.")
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
            "Authorization": "Bearer " + read_token(self.token_file), "Content-Type": "application/json"})
        try:
            try:
                response = self.opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status = response.status
                if 300 <= status < 400:
                    raise ProductError(3, "redirect_refused", "Coordinator redirects are refused; verify its origin explicitly.")
                raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ProductError(3, "response_too_large", "Coordinator response exceeds the transport limit.")
            if 300 <= status < 400:
                raise ProductError(3, "redirect_refused", "Coordinator redirects are refused; verify its origin explicitly.")
            result = json.loads(raw)
            if (not isinstance(result, dict) or type(result.get("protocol")) is not int
                    or result["protocol"] != 1 or type(result.get("ok")) is not bool):
                raise ValueError("Unsupported response")
            if not result["ok"]:
                if (type(result.get("exit_code")) is not int or result["exit_code"] not in {2, 3, 4, 5}
                        or not isinstance(result.get("code"), str) or not result["code"]
                        or not isinstance(result.get("message"), str) or not isinstance(result.get("data", {}), dict)):
                    raise ValueError("Invalid error envelope")
                raise ProductError(result["exit_code"], result["code"], result["message"], data=result.get("data", {}))
            if status != 200 or not isinstance(result.get("data"), dict):
                raise ValueError("Invalid successful response")
            return result["data"]
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProductError(5, "coordinator_unavailable", "Coordinator is unavailable; keep local drafts and retry after reconnecting.") from exc
        except (ValueError, UnicodeError) as exc:
            raise ProductError(3, "protocol_invalid", "Coordinator returned an invalid protocol response.") from exc


class CoordinatorApp:
    """Small ASGI boundary; engine enforces membership and operation authority."""
    def __init__(self, db_path):
        self.db_path = Path(db_path)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        status = 200
        try:
            if scope.get("method") != "POST" or scope.get("path") != "/v1/request":
                raise ProductError(3, "route_invalid", "Only POST /v1/request is available.")
            headers = {}
            for key, value in scope.get("headers", []):
                if key.lower() in headers:
                    raise ProductError(3, "headers_invalid", "Duplicate request headers are unsupported.")
                headers[key.lower()] = value
            authorization = headers.get(b"authorization", b"").decode("ascii")
            if not authorization.startswith("Bearer ") or not 32 <= len(authorization[7:]) <= 512:
                raise ProductError(4, "unauthorized", "Valid project membership is required.")
            if headers.get(b"content-type", b"").split(b";", 1)[0] != b"application/json":
                raise ProductError(3, "content_type_invalid", "JSON requests are required.")
            body = bytearray()
            deadline = asyncio.get_running_loop().time() + 30
            while True:
                try:
                    event = await asyncio.wait_for(receive(), max(0.01, deadline - asyncio.get_running_loop().time()))
                except TimeoutError as exc:
                    raise ProductError(5, "request_timeout", "Request body did not arrive within 30 seconds.") from exc
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > MAX_BODY:
                    raise ProductError(3, "payload_too_large", "Request exceeds 128 MiB.")
                if not event.get("more_body"):
                    break
            request = json.loads(body)
            if (not isinstance(request, dict) or set(request) != {"protocol", "operation", "payload"}
                    or type(request["protocol"]) is not int or request["protocol"] != 1
                    or not isinstance(request["operation"], str) or not isinstance(request["payload"], dict)):
                raise ProductError(3, "protocol_invalid", "Unsupported request schema.")
            from .engine import Coordinator
            data = await asyncio.to_thread(Coordinator(self.db_path).request,
                                           authorization[7:], request["operation"], request["payload"])
            result = {"protocol": 1, "ok": True, "data": data}
        except ProductError as exc:
            status = 403 if exc.exit_code == 4 else 400 if exc.exit_code in {2, 3} else 503
            result = {"protocol": 1, "ok": False, "exit_code": exc.exit_code,
                      "code": exc.code, "message": str(exc), "data": exc.data}
        except (ValueError, UnicodeError, TypeError):
            status = 400
            result = {"protocol": 1, "ok": False, "exit_code": 3, "code": "protocol_invalid", "message": "Malformed request."}
        except Exception:
            status = 500
            result = {"protocol": 1, "ok": False, "exit_code": 5, "code": "coordinator_error", "message": "Coordinator could not complete the request; retry using the same operation identity."}
        encoded = json.dumps(result, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]})
        await send({"type": "http.response.body", "body": encoded})


def serve(db_path, host="127.0.0.1", port=8765, certfile=None, keyfile=None):
    if not Path(db_path).is_file():
        raise ProductError(5, "coordinator_missing", "Initialize the coordinator before serving it.")
    if not loopback(host) and not (certfile and keyfile):
        raise ProductError(3, "tls_required", "Non-loopback serving requires an explicit TLS certificate and private key.")
    try:
        import uvicorn
    except ImportError as exc:
        raise ProductError(5, "server_dependency_missing", "Serving requires the optional pinned Uvicorn dependency in a dedicated runtime environment.") from exc
    from .engine import Coordinator
    Coordinator(db_path).recover()
    uvicorn.run(CoordinatorApp(db_path), host=host, port=port, ssl_certfile=certfile,
                ssl_keyfile=keyfile, proxy_headers=False, access_log=False,
                lifespan="off", limit_concurrency=32, timeout_keep_alive=5,
                timeout_graceful_shutdown=30, log_level="warning")

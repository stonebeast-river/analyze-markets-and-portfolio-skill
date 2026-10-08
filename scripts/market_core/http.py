from __future__ import annotations

import gzip
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any


class DataSourceError(RuntimeError):
    pass


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    secret_names = {"api_key", "apikey", "key", "token", "access_token", "secret", "authorization"}
    query = [(key, "REDACTED" if key.lower() in secret_names else value)
             for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)]
    host = parsed.netloc.rsplit("@", 1)[-1]
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, urllib.parse.urlencode(query), ""))


def redact_error(value: str) -> str:
    return re.sub(r"(?i)((?:api_?key|access_token|token|secret|authorization)=)[^&\s'\"]+", r"\1REDACTED", str(value))


@dataclass
class HttpClient:
    user_agent: str = "market-research-skill/0.4 (personal research)"
    timeout: float = 15.0
    retries: int = 2
    min_interval_by_host: dict[str, float] = field(default_factory=dict)
    archive: Any = None
    cache_ttl_by_host: dict[str, float] = field(default_factory=dict)
    max_response_bytes: int = 67108864

    def __post_init__(self) -> None:
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_response_receipt = None

    def _throttle(self, host: str) -> None:
        interval = float(self.min_interval_by_host.get(host, 0.0))
        if interval <= 0:
            return
        with self._lock:
            elapsed = time.monotonic() - self._last_call.get(host, 0.0)
            if elapsed < interval:
                time.sleep(interval - elapsed)
            self._last_call[host] = time.monotonic()

    def source_receipts(self):
        """Snapshot the successful response just consumed by a parser, never prior requests."""
        receipt = self.last_response_receipt
        if not self.archive or not receipt or receipt.get('status') not in {'http_ok', 'cache_hit'}:
            return []
        fields = ('receipt_path', 'receipt_sha256', 'decoded_sha256', 'request_id', 'received_at',
                  'request_url', 'transport')
        if any(not receipt.get(key) for key in fields):
            raise DataSourceError('Successful archived response lacks a complete row reference')
        return [{'archive_directory': str(self.archive.directory), **{key: receipt[key] for key in fields}}]

    def bind_rows(self, rows, receipts=None):
        """Bind explicit response dependencies while still in the parsing scope."""
        references = self.source_receipts() if receipts is None else receipts
        unique = {item['receipt_sha256']: dict(item) for item in references}
        for row in rows:
            row.source_receipts = [dict(item) for item in unique.values()]
        return rows

    def get_bytes(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        form: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        if params:
            query = urllib.parse.urlencode(params)
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        parsed = urllib.parse.urlparse(url)
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip",
        }
        request_headers.update(headers or {})
        form_bytes=urllib.parse.urlencode(form).encode('utf-8') if form is not None else None
        method='POST' if form_bytes is not None else 'GET'
        namespace_headers=dict(request_headers)
        if form_bytes is not None:
            import hashlib
            namespace_headers['X-Request-Body-SHA256']=hashlib.sha256(form_bytes).hexdigest()
        request_id=self.archive.request_id(url,namespace_headers) if self.archive else ''
        self.last_response_receipt=None
        if self.archive:
            cached=self.archive.cached(request_id,max_age_seconds=float(self.cache_ttl_by_host.get(parsed.hostname,0)))
            if cached:
                payload,final,self.last_response_receipt=cached;return payload,final
        self._throttle(parsed.netloc)
        secret_names={'api_key','apikey','key','token','access_token','secret','authorization'}
        secrets=[value for key,value in urllib.parse.parse_qsl(parsed.query) if key.lower() in secret_names and value]
        secrets.extend(str(value) for key,value in (form or {}).items() if key.lower() in secret_names and value)
        secrets.extend(value for key,value in request_headers.items() if key.lower()=='authorization' and value)
        secrets.extend(value.split()[-1] for key,value in request_headers.items() if key.lower()=='authorization' and value)
        safe_headers={'content-type','content-encoding','content-length','date','etag','last-modified','cache-control','expires'}

        def archive_response(response,wire,payload,status,cacheable=True):
            if not self.archive:return
            if (not cacheable and secrets) or any(secret.encode('utf-8') in payload for secret in secrets):
                self.last_response_receipt=self.archive.failure(request_id,redact_url(url),'Response echoed a request credential; raw payload not written',status='credential_echo_not_archived')
                return
            self.last_response_receipt=self.archive.store(request_id,redact_url(url),redact_url(response.geturl()),wire,payload,
                headers={key:value for key,value in response.headers.items() if key.lower() in safe_headers},status=status,cacheable=cacheable)

        def decode(response,wire):
            encoding=response.headers.get('Content-Encoding','').lower()
            try:
                if encoding=='gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(wire)) as handle:payload=handle.read(self.max_response_bytes+1)
                elif encoding in {'','identity'}:payload=wire
                else:raise DataSourceError('Unsupported HTTP content encoding: '+encoding)
                if len(payload)>self.max_response_bytes:raise DataSourceError('Decoded HTTP response exceeds configured size limit')
                return payload
            except (OSError,EOFError,zlib.error,DataSourceError) as exc:
                archive_response(response,wire,wire,int(getattr(response,'status',200)),cacheable=False)
                raise DataSourceError('HTTP response decoding failed: '+str(exc)) from None

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(url, headers=request_headers,data=form_bytes,method=method)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    wire=response.read(self.max_response_bytes+1)
                    if len(wire)>self.max_response_bytes:
                        if self.archive:self.archive.failure(request_id,redact_url(url),'HTTP response exceeds configured size limit',status='response_over_limit')
                        raise DataSourceError('HTTP response exceeds configured size limit')
                    payload=decode(response,wire)
                    archive_response(response,wire,payload,int(getattr(response,'status',200)))
                    return payload, redact_url(response.geturl())
            except urllib.error.HTTPError as exc:
                last_error=exc
                wire=exc.read(self.max_response_bytes+1)
                if len(wire)<=self.max_response_bytes:
                    payload=decode(exc,wire)
                    archive_response(exc,wire,payload,exc.code)
                if attempt<self.retries:time.sleep(0.6*(2**attempt))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.6 * (2**attempt))
        message=redact_error(str(last_error))
        for secret in secrets:message=message.replace(secret,'REDACTED')
        if self.archive:self.last_response_receipt=self.archive.failure(request_id,redact_url(url),message)
        raise DataSourceError(f"{method} failed for {parsed.hostname}: {message}")

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> tuple[str, str]:
        payload, final_url = self.get_bytes(url, params=params, headers=headers)
        return payload.decode(encoding, errors="replace"), final_url

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        text, final_url = self.get_text(url, params=params, headers=headers)
        try:
            return json.loads(text), final_url
        except json.JSONDecodeError as exc:
            if self.archive and self.last_response_receipt:
                self.archive.reject(self.last_response_receipt,'JSON decoding failed')
            raise DataSourceError(f"Invalid JSON from {redact_url(final_url)}: {exc}") from None

    def post_form_json(self,url,form,*,headers=None):
        """Read a public form-query endpoint; its body has a separate cache namespace."""
        body,source=self.get_bytes(url,form=form,headers={'Content-Type':'application/x-www-form-urlencoded',**(headers or {})})
        try:return json.loads(body.decode('utf-8')),source
        except (UnicodeDecodeError,json.JSONDecodeError) as error:
            if self.archive and self.last_response_receipt:self.archive.reject(self.last_response_receipt,'Form-query JSON decoding failed')
            raise DataSourceError('Invalid form-query JSON from '+redact_url(source)) from error

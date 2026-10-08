"""Independent public-source reads restricted to explicitly configured HTTPS hosts."""
import hashlib
import ipaddress
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip-1)
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def validate_url(url, allowed_hosts):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError("Source must be public HTTPS without credentials")
    if parsed.hostname not in allowed_hosts or parsed.hostname in ("localhost",):
        raise ValueError("Source host is outside the authorized whitelist")
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise ValueError("Private source addresses are prohibited")
    except ValueError as e:
        if "Private" in str(e):
            raise

def fetch(specification, allowed_hosts):
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate_url(newurl, allowed_hosts)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    results = []
    opener = urllib.request.build_opener(Redirect())
    for source in specification:
        validate_url(source["url"], allowed_hosts)
        request = urllib.request.Request(source["url"], headers={"User-Agent": "native-orchestrator-source-check/0.1"})
        with opener.open(request, timeout=20) as response:
            validate_url(response.url, allowed_hosts)
            raw = response.read(262145)
            if len(raw) > 262144:
                raise ValueError("Source response exceeds 256 KiB evidence budget")
            body = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            if "html" in response.headers.get("Content-Type", ""):
                parser = Text()
                parser.feed(body)
                body = " ".join(parser.parts)
        if not all(term in body for term in source.get("required_terms", [])):
            raise ValueError("SOURCE_UNVERIFIED: required source terms missing")
        results.append({"id": source["id"], "url": source["url"], "read_at": time.time(),
            "response_sha256": hashlib.sha256(raw).hexdigest(), "required_terms_found": True,
            "body_text": body[:100000], "evidence_type": "INDEPENDENT_HTTP_READ"})
    return results

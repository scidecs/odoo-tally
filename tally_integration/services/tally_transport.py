# -*- coding: utf-8 -*-
"""Direct HTTP(S) transport to a TallyPrime XML gateway — no on-prem agent.

Primary topology (≈90% of deployments): Tally runs on a cloud Windows host with a
routable address, and Odoo (Odoo.sh or self-hosted) connects to it directly. For a
Tally sitting on a local PC, expose it with a tunnel (ngrok / cloudflared) or a
reverse proxy and point the instance's Base URL at that.

Tally's gateway has NO authentication of its own, so this transport supports Basic
Auth or a custom secret header (validated by the proxy/tunnel in front of Tally)
and HTTPS. Stdlib only — no 'requests' dependency.
"""
import base64
import logging
import re
import ssl
import urllib.error
import urllib.request

_logger = logging.getLogger(__name__)


class TallyTransportError(Exception):
    pass


def post_xml(url, xml, timeout=30, auth=None, extra_headers=None, verify=True):
    """POST an XML envelope to a Tally endpoint; return the decoded response text.

    :param url: full endpoint URL, e.g. http://13.234.x.x:9000 or https://acme-tally.example.com
    :param auth: optional (username, password) tuple for HTTP Basic Auth
    :param extra_headers: optional dict of extra headers (e.g. a secret token header)
    :param verify: verify TLS certificate for HTTPS endpoints
    """
    data = (xml or "").encode("utf-8")
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "Content-Length": str(len(data)),
        "Connection": "close",
    }
    if auth and auth[0]:
        token = base64.b64encode(("%s:%s" % (auth[0], auth[1] or "")).encode("utf-8")).decode("ascii")
        headers["Authorization"] = "Basic " + token
    if extra_headers:
        headers.update({k: v for k, v in extra_headers.items() if k})

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)

    context = None
    if url.lower().startswith("https") and not verify:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise TallyTransportError("Tally endpoint %s returned HTTP %s" % (url, e.code))
    except urllib.error.URLError as e:
        raise TallyTransportError("Cannot reach Tally at %s: %s" % (url, getattr(e, "reason", e)))
    except Exception as e:  # noqa: BLE001 - surface any socket/timeout error uniformly
        raise TallyTransportError("Tally request failed (%s): %s" % (url, e))

    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_import_response(text):
    """Extract created/altered/error counts (and any LINEERROR) from an import reply."""
    def _int(tag):
        m = re.search(r"<%s>(-?\d+)</%s>" % (tag, tag), text or "")
        return int(m.group(1)) if m else 0

    line_error = None
    m = re.search(r"<LINEERROR>(.*?)</LINEERROR>", text or "", re.S)
    if m:
        line_error = m.group(1).strip()
    errors = _int("ERRORS") or _int("EXCEPTIONS") or (1 if line_error else 0)
    return {
        "created": _int("CREATED"),
        "altered": _int("ALTERED"),
        "errors": errors,
        "line_error": line_error,
    }

import base64
import os
import sys
from typing import TYPE_CHECKING

from ddtrace.appsec import _asm_request_context
from ddtrace.constants import APPSEC_ENV
from ddtrace.internal.compat import parse
from ddtrace.internal.compat import to_bytes_py2
from ddtrace.internal.constants import APPSEC_BLOCKED_RESPONSE_HTML
from ddtrace.internal.constants import APPSEC_BLOCKED_RESPONSE_JSON
from ddtrace.internal.logger import get_logger
from ddtrace.internal.utils.formats import asbool


if TYPE_CHECKING:  # pragma: no cover
    from typing import Any
    from typing import Optional

    from ddtrace import Tracer
    from ddtrace.internal.compat import text_type as unicode


log = get_logger(__name__)


def _appsec_rc_features_is_enabled():
    # type: () -> bool
    if asbool(os.environ.get("DD_REMOTE_CONFIGURATION_ENABLED", "true")):
        return APPSEC_ENV not in os.environ
    return False


def _appsec_rc_capabilities(test_tracer=None):
    # type: (Optional[Tracer]) -> str
    r"""return the bit representation of the composed capabilities in base64
    bit 0: Reserved
    bit 1: ASM 1-click Activation
    bit 2: ASM Ip blocking

    Int Number  -> binary number    -> bytes representation -> base64 representation
    ASM Activation:
    2           -> 10               -> b'\x02'              -> "Ag=="
    ASM Ip blocking:
    4           -> 100              -> b'\x04'              -> "BA=="
    ASM Activation and ASM Ip blocking:
    6           -> 110              -> b'\x06'              -> "Bg=="
    ...
    256         -> 100000000        -> b'\x01\x00'          -> b'AQA='
    """
    if test_tracer is None:
        from ddtrace import tracer
    else:
        tracer = test_tracer

    value = 0b0
    result = ""
    if asbool(os.environ.get("DD_REMOTE_CONFIGURATION_ENABLED", "true")):
        if _appsec_rc_features_is_enabled():
            value |= 1 << 1  # Enable ASM_ACTIVATION
        if tracer._appsec_processor:
            value |= 1 << 2  # Enable ASM_IP_BLOCKING
            value |= 1 << 3  # Enable ASM_DD_RULES
            value |= 1 << 4  # Enable ASM_EXCLUSIONS
            value |= 1 << 5  # Enable ASM_REQUEST_BLOCKING
            value |= 1 << 6  # Enable ASM_ASM_RESPONSE_BLOCKING
            value |= 1 << 7  # Enable ASM_USER_BLOCKING
            value |= 1 << 8  # Enable ASM_CUSTOM_RULES

        if sys.version_info.major < 3:
            bytes_res = to_bytes_py2(value, (value.bit_length() + 7) // 8, "big")
            # "type: ignore" because mypy does not notice this is for Python2 b64encode
            result = str(base64.b64encode(bytes_res))  # type: ignore
        else:
            result = str(base64.b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")), encoding="utf-8")

    return result


_HTML_BLOCKED_TEMPLATE_CACHE = None  # type: Optional[str]
_JSON_BLOCKED_TEMPLATE_CACHE = None  # type: Optional[str]


def _get_blocked_template(accept_header_value):
    # type: (str) -> str

    global _HTML_BLOCKED_TEMPLATE_CACHE
    global _JSON_BLOCKED_TEMPLATE_CACHE

    need_html_template = False

    if accept_header_value and "text/html" in accept_header_value.lower():
        need_html_template = True

    if need_html_template and _HTML_BLOCKED_TEMPLATE_CACHE:
        return _HTML_BLOCKED_TEMPLATE_CACHE

    if not need_html_template and _JSON_BLOCKED_TEMPLATE_CACHE:
        return _JSON_BLOCKED_TEMPLATE_CACHE

    if need_html_template:
        template_path = os.getenv("DD_APPSEC_HTTP_BLOCKED_TEMPLATE_HTML")
    else:
        template_path = os.getenv("DD_APPSEC_HTTP_BLOCKED_TEMPLATE_JSON")

    if template_path:
        try:
            with open(template_path, "r") as template_file:
                content = template_file.read()

            if need_html_template:
                _HTML_BLOCKED_TEMPLATE_CACHE = content
            else:
                _JSON_BLOCKED_TEMPLATE_CACHE = content
            return content
        except (OSError, IOError) as e:
            log.warning("Could not load custom template at %s: %s", template_path, str(e))  # noqa: G200

    # No user-defined template at this point
    if need_html_template:
        _HTML_BLOCKED_TEMPLATE_CACHE = APPSEC_BLOCKED_RESPONSE_HTML
        return APPSEC_BLOCKED_RESPONSE_HTML

    _JSON_BLOCKED_TEMPLATE_CACHE = APPSEC_BLOCKED_RESPONSE_JSON
    return APPSEC_BLOCKED_RESPONSE_JSON


def parse_form_params(body):
    # type: (unicode) -> dict[unicode, unicode|list[unicode]]
    """Return a dict of form data after HTTP form parsing"""
    body_params = body.replace("+", " ")
    req_body = dict()  # type: dict[unicode, unicode|list[unicode]]
    for item in body_params.split("&"):
        key, equal, val = item.partition("=")
        if equal:
            key = parse.unquote(key)
            val = parse.unquote(val)
            prev_value = req_body.get(key, None)
            if prev_value is None:
                req_body[key] = val
            elif isinstance(prev_value, list):
                prev_value.append(val)
            else:
                req_body[key] = [prev_value, val]
    return req_body


def parse_form_multipart(body):
    # type: (unicode) -> dict[unicode, Any]
    """Return a dict of form data after HTTP form parsing"""
    import email
    import json

    import xmltodict

    def parse_message(msg):
        if msg.is_multipart():
            res = {
                part.get_param("name", failobj=part.get_filename(), header="content-disposition"): parse_message(part)
                for part in msg.get_payload()
            }
        else:
            content_type = msg.get("Content-Type")
            if content_type in ("application/json", "text/json"):
                res = json.loads(msg.get_payload())
            elif content_type in ("application/xml", "text/xml"):
                res = xmltodict.parse(msg.get_payload())
            elif content_type in ("text/plain", None):
                res = msg.get_payload()
            else:
                res = ""

        return res

    headers = _asm_request_context.get_headers()
    if headers is not None:
        content_type = headers.get("Content-Type")
        msg = email.message_from_string("MIME-Version: 1.0\nContent-Type: %s\n%s" % (content_type, body))
        return parse_message(msg)
    return {}

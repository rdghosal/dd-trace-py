import json
import os

import pytest

from ddtrace.appsec._remoteconfiguration import appsec_rc_reload_features
from ddtrace.appsec.utils import _appsec_rc_capabilities
from ddtrace.appsec.utils import _appsec_rc_features_is_enabled
from ddtrace.constants import APPSEC_ENV
from ddtrace.constants import APPSEC_JSON
from ddtrace.contrib.trace_utils import set_http_meta
from ddtrace.ext import SpanTypes
from ddtrace.internal import _context
from ddtrace.internal.remoteconfig import RemoteConfig
from tests.appsec.test_processor import Config
from tests.utils import override_env


def _set_and_get_appsec_tags(tracer):
    with tracer.trace("test", span_type=SpanTypes.WEB) as span:
        set_http_meta(
            span,
            {},
            raw_uri="http://example.com/.git",
            status_code="404",
            request_cookies={"cookie1": "im the cookie1"},
        )
    return span.get_tag(APPSEC_JSON)


def test_rc_enabled_by_default(tracer):
    result = _set_and_get_appsec_tags(tracer)
    assert result is None
    assert _appsec_rc_features_is_enabled()


def test_rc_activate_is_active_and_get_processor_tags(tracer):
    result = _set_and_get_appsec_tags(tracer)
    assert result is None
    appsec_rc_reload_features(tracer)(None, {"asm": {"enabled": True}})
    assert "triggers" in _set_and_get_appsec_tags(tracer)


@pytest.mark.parametrize(
    "appsec_enabled, rc_value",
    [
        ("", True),
        ("true", True),
    ],
)
def test_rc_activation_states_on(tracer, appsec_enabled, rc_value):
    tracer.configure(appsec_enabled=False)
    with override_env({APPSEC_ENV: appsec_enabled}):
        if appsec_enabled == "":
            del os.environ[APPSEC_ENV]

        appsec_rc_reload_features(tracer)(None, {"asm": {"enabled": rc_value}})
        result = _set_and_get_appsec_tags(tracer)
        assert "triggers" in result


@pytest.mark.parametrize(
    "appsec_enabled, rc_value",
    [
        ("", False),
        ("false", False),
        ("false", True),
        ("true", False),
    ],
)
def test_rc_activation_states_off(tracer, appsec_enabled, rc_value):
    tracer.configure(appsec_enabled=True)
    with override_env({APPSEC_ENV: appsec_enabled}):
        if appsec_enabled == "":
            del os.environ[APPSEC_ENV]

        rc_config = {"asm": {"enabled": True}}
        if rc_value is False:
            rc_config = False

        appsec_rc_reload_features(tracer)(None, rc_config)
        result = _set_and_get_appsec_tags(tracer)
        assert result is None


@pytest.mark.parametrize(
    "rc_enabled, capability",
    [
        ("true", "Bg=="),
        ("false", ""),
    ],
)
def test_rc_capabilities(rc_enabled, capability):
    with override_env({"DD_REMOTE_CONFIGURATION_ENABLED": rc_enabled}):
        assert _appsec_rc_capabilities() == capability


def test_rc_activation_validate_products(tracer):
    tracer.configure(appsec_enabled=False)

    rc_config = {"asm": {"enabled": True}}

    assert not RemoteConfig._worker

    appsec_rc_reload_features(tracer)(None, rc_config)

    assert RemoteConfig._worker._client._products["ASM_DATA"]


def test_rc_activation_ip_blocking_data(tracer):
    with override_env({APPSEC_ENV: "true"}):
        tracer.configure(appsec_enabled=True)
        rc_config = {
            "rules_data": [
                {
                    "data": [{"expiration": 1755346879, "value": "user8"}],
                    "id": "blocked_users",
                    "type": "data_with_expiration",
                },
                {
                    "data": [
                        {"value": "8.8.4.4"},
                    ],
                    "id": "blocked_ips",
                    "type": "ip_with_expiration",
                },
            ]
        }

        assert not RemoteConfig._worker

        appsec_rc_reload_features(tracer)(None, rc_config)

        with tracer.trace("test", span_type=SpanTypes.WEB, peer_ip="8.8.4.4", headers={}) as span:
            set_http_meta(
                span,
                Config(),
            )
        assert "triggers" in json.loads(span.get_tag(APPSEC_JSON))
        assert _context.get_item("http.request.remote_ip", span) == "8.8.4.4"

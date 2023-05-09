import platform
import sys
from typing import Dict
from typing import List
from typing import Tuple

import ddtrace
from ddtrace.internal.compat import PY3
from ddtrace.internal.constants import DEFAULT_SERVICE_NAME
from ddtrace.internal.packages import get_distributions
from ddtrace.internal.runtime.container import get_container_info
from ddtrace.internal.utils.cache import cached
from ddtrace.internal.utils.cache import callonce

from ...settings import _config as config
from ..hostname import get_hostname


_platform = callonce(lambda: platform.platform(aliased=True, terse=True))()


def _format_version_info(vi):
    # type: (sys._version_info) -> str
    """Converts sys.version_info into a string with the format x.x.x"""
    return "%d.%d.%d" % (vi.major, vi.minor, vi.micro)


def _get_container_id():
    # type: () -> str
    """Get ID from docker container"""
    container_info = get_container_info()
    if container_info:
        return container_info.container_id or ""
    return ""


def _get_os_version():
    # type: () -> str
    """Returns the os version for applications running on Unix, Mac or Windows 32-bit"""
    try:
        mver, _, _ = platform.mac_ver()
        if mver:
            return mver

        _, wver, _, _ = platform.win32_ver()
        if wver:
            return wver

        # This is the call which is more likely to fail
        #
        # https://docs.python.org/3/library/platform.html#unix-platforms
        #   Note that this function has intimate knowledge of how different libc versions add symbols
        #   to the executable is probably only usable for executables compiled using gcc.
        _, lver = platform.libc_ver()
        if lver:
            return lver
    except OSError:
        # We were unable to lookup the proper version
        pass

    return ""


@cached()
def _get_application(key):
    # type: (Tuple[str, str, str]) -> Dict
    """
    This helper packs and unpacks get_application arguments to support caching.
    Cached() annotation only supports functions with one argument
    """
    service, version, env = key

    return {
        "service_name": service or DEFAULT_SERVICE_NAME,  # mandatory field, can not be empty
        "service_version": version or "",
        "env": env or "",
        "language_name": "python",
        "language_version": _format_version_info(sys.version_info),
        "tracer_version": ddtrace.__version__,
        "runtime_name": platform.python_implementation(),
        "runtime_version": _format_version_info(sys.implementation.version) if PY3 else "",
        "products": _get_products(),
    }


def get_dependencies():
    # type: () -> List[Dict[str, str]]
    """Returns a unique list of the names and versions of all installed packages"""
    dependencies = {(dist.name, dist.version) for dist in get_distributions()}
    return [{"name": name, "version": version} for name, version in dependencies]


def get_application(service, version, env):
    # type: (str, str, str) -> Dict
    """Creates a dictionary to store application data using ddtrace configurations and the System-Specific module"""
    # We cache the application dict to reduce overhead since service, version, or env configurations
    # can change during runtime
    return _get_application((service, version, env))


def _get_products():
    # type: () -> Dict
    return {
        "appsec": {"version": ddtrace.__version__, "enabled": config._appsec_enabled},
    }


_host_info = None


def get_host_info():
    # type: () -> Dict
    """Creates a dictionary to store host data using the platform module"""
    global _host_info
    if _host_info is None:
        _host_info = {
            "os": _platform,
            "hostname": get_hostname(),
            "os_version": _get_os_version(),
            "kernel_name": platform.system(),
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "container_id": _get_container_id(),
        }
    return _host_info

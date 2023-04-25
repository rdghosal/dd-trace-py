from types import CodeType
from types import FrameType

from ddtrace.internal.logger import get_logger
from ddtrace.datadog import ddup


log = get_logger(__name__)


cpdef _extract_class_name(frame):
    # type: (...) -> str
    """Extract class name from a frame, if possible.

    :param frame: The frame object.
    """
    if frame.f_code.co_varnames:
        argname = frame.f_code.co_varnames[0]
        try:
            value = frame.f_locals[argname]
        except KeyError:
            return ""
        try:
            if argname == "self":
                return object.__getattribute__(type(value), "__name__")  # use type() and object.__getattribute__ to avoid side-effects
            if argname == "cls":
                return object.__getattribute__(value, "__name__")
        except AttributeError:
            return ""
    return ""


cpdef traceback_to_frames(traceback, max_nframes, use_libdatadog, use_pyprof):
    """Serialize a Python traceback object into a list of tuple of (filename, lineno, function_name).

    :param traceback: The traceback object to serialize.
    :param max_nframes: The maximum number of frames to return.
    :param use_libdatadog: Whether to use libdatadog for stack collection, rather than returning
    :param use_pyprof: prepare frames for use in the Python profiler
    :return: The serialized frames and the number of frames present in the original traceback.
    """
    tb = traceback
    frames = []
    nframes = 0
    if tb is not None and tb.tb_frame is not None and use_libdatadog:
        ddup.push_classinfo(_extract_class_name(tb.tb_frame))

    while tb is not None:
        if nframes < max_nframes:
            frame = tb.tb_frame
            code = frame.f_code
            lineno = 0 if frame.f_lineno is None else frame.f_lineno
            if use_libdatadog:
                ddup.push_frame(code.co_name, code.co_filename, 0, lineno)
            if use_pyprof:
                frames.insert(0, (code.co_filename, lineno, code.co_name, _extract_class_name(frame)))
        nframes += 1
        tb = tb.tb_next
    return frames, nframes


cpdef pyframe_to_frames(frame, max_nframes, use_libdatadog, use_pyprof):
    """Convert a Python frame to a list of frames.

    :param frame: The frame object to serialize.
    :param max_nframes: The maximum number of frames to return.
    :param use_libdatadog: Whether to use libdatadog for stack collection, rather than returning
    :param use_pyprof: prepare frames for use in the Python profiler
    :return: The serialized frames and the number of frames present in the original traceback."""
    # DEV: There are reports that Python 3.11 returns non-frame objects when
    # retrieving frame objects and doing stack unwinding. If we detect a
    # non-frame object we log a warning and return an empty stack, to avoid
    # reporting potentially incomplete and/or inaccurate data. This until we can
    # come to the bottom of the issue.
    if not isinstance(frame, FrameType):
        log.warning(
            "Got object of type '%s' instead of a frame object for the top frame of a thread", type(frame).__name__
        )
        return [], 0

    frames = []
    nframes = 0

    if frame is not None and use_libdatadog:
        ddup.push_classinfo(_extract_class_name(frame))

    while frame is not None:
        IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 11):
            if not isinstance(frame, FrameType):
                log.warning(
                    "Got object of type '%s' instead of a frame object during stack unwinding", type(frame).__name__
                )
                return [], 0

        if nframes < max_nframes:
            code = frame.f_code
            IF PY_MAJOR_VERSION > 3 or (PY_MAJOR_VERSION == 3 and PY_MINOR_VERSION >= 11):
                if not isinstance(code, CodeType):
                    log.warning(
                        "Got object of type '%s' instead of a code object during stack unwinding", type(code).__name__
                    )
                    return [], 0

            lineno = 0 if frame.f_lineno is None else frame.f_lineno
            if use_libdatadog:
                ddup.push_frame(code.co_name, code.co_filename, 0, lineno)
            if use_pyprof:
                frames.append((code.co_filename, lineno, code.co_name, _extract_class_name(frame)))
        nframes += 1
        frame = frame.f_back

    if use_libdatadog:
        omitted = nframes - max_nframes
        if omitted > 0:
            ddup.push_frame("<%d frame%s omitted>" % (omitted, ("s" if omitted > 1 else "")), "", 0, 0)
    return frames, nframes

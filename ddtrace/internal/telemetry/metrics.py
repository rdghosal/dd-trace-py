import abc
import time
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import six
from typing_extensions import Literal

from ..hostname import get_hostname


MetricType = Literal["count", "gauge", "rate"]
MetricTagType = Dict[str, str]


class Metric(six.with_metaclass(abc.ABCMeta)):
    """
    stores metrics which will be sent to the Telemetry Intake metrics to the Datadog Instrumentation Telemetry Org
    """

    HOST_NAME = get_hostname()

    def __init__(self, namespace, name, metric_type, tags, common, interval=None):
        # type: (str, str, MetricType, MetricTagType, bool, Optional[int]) -> None
        """
        name: metric name
        metric_type: type of metric (count/gauge/rate)
        common: set to True if a metric is common to all tracers, false if it is python specific
        interval: field set for gauge and rate metrics, any field set is ignored for count metrics (in secs)
        """
        self.name = name
        self.type = metric_type
        self.common = common
        self.interval = interval
        self._roll_up_interval = interval
        self.namespace = namespace
        self._points = []  # type: List[Tuple[int, int]]
        self._tags = tags  # type: MetricTagType
        self._count = 0.0

    @property
    def id(self):
        """
        https://www.datadoghq.com/blog/the-power-of-tagged-metrics/#whats-a-metric-tag
        """
        return "".join([self.name, str(self._tags)])

    def __hash__(self):
        return self.id

    @abc.abstractmethod
    def add_point(self, value=1.0):
        # type: (float) -> None
        """adds timestamped data point associated with a metric"""
        pass

    def set_tags(self, tags):
        # type: (Dict) -> None
        """sets a metrics tag"""
        self._tags = tags

    def set_tag(self, name, value):
        # type: (str, str) -> None
        """sets a metrics tag"""
        self._tags[name] = value

    def to_dict(self):
        # type: () -> Dict
        """returns a dictionary containing the metrics fields expected by the telemetry intake service"""
        return {
            "host": self.HOST_NAME,
            "name": self.name,
            "type": self.type,
            "common": self.common,
            "interval": int(self.interval),
            "points": self._points,
            "tags": self._tags,
        }


class CountMetric(Metric):
    """A count type adds up all the submitted values in a time interval. This would be suitable for a
    metric tracking the number of website hits, for instance."""

    def add_point(self, value=1.0):
        # type: (float) -> None
        """adds timestamped data point associated with a metric"""
        timestamp = int(time.time())
        # self._count += 1.0
        # self._points = [(timestamp, self._count)]
        self._points.append((timestamp, float(value)))


class GaugeMetric(Metric):
    """
    A gauge type takes the last value reported during the interval. This type would make sense for tracking RAM or
    CPU usage, where taking the last value provides a representative picture of the host’s behavior during the time
    interval. In this case, using a different type such as count would probably lead to inaccurate and extreme values.
    Choosing the correct metric type ensures accurate data.
    """

    def add_point(self, value=1.0):
        # type: (float) -> None
        """adds timestamped data point associated with a metric"""
        timestamp = int(time.time())
        self._points = [(timestamp, float(value))]
        # self._points.append((timestamp, value))


class RateMetric(Metric):
    """
    The rate type takes the count and divides it by the length of the time interval. This is useful if you’re
    interested in the number of hits per second.
    """

    def add_point(self, value=1.0):
        # type: (float) -> None
        """Example:
        https://github.com/DataDog/datadogpy/blob/ee5ac16744407dcbd7a3640ee7b4456536460065/datadog/threadstats/metrics.py#L181
        """
        timestamp = int(time.time())
        self._count += value
        self._points = [(timestamp, self._count / float(self.interval))]

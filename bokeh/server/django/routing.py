import re
from typing import Dict, List

from django.conf.urls import url
from django.urls.resolvers import URLPattern
from channels.http import AsgiHandler

from bokeh.server.contexts import ApplicationContext
from .consumers import BokehAppHTTPConsumer, BokehAppWebsocketConsumer

class RoutingConfiguration(object):

    _http_urlpatterns = []
    _websocket_urlpatterns = []

    _prefix = "bokehapps"

    def __init__(self, app_contexts: Dict[str, ApplicationContext]):

        for k, v in app_contexts.items():
            k = k.replace('/', '')
            self._add_new_routing(k, v)

    def get_http_urlpatterns(self) -> List[URLPattern]:
        return self._http_urlpatterns + [url(r"", AsgiHandler)]

    def get_websocket_urlpatterns(self) -> List[URLPattern]:
        return self._websocket_urlpatterns

    def _add_new_routing(self, app_name: str, app_context: ApplicationContext) -> None:
        kwargs = dict(app_context=app_context)

        def urlpattern(suffix=""):
            prefix = self._prefix + "/" if self._prefix else ""
            return r"^{}{}{}$".format(prefix, re.escape(app_name), suffix)

        self._http_urlpatterns.append(url(urlpattern(), BokehAppHTTPConsumer, kwargs=kwargs))
        self._websocket_urlpatterns.append(url(urlpattern("/ws"), BokehAppWebsocketConsumer, kwargs=kwargs))

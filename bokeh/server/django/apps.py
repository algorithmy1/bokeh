import os
import glob
import asyncio

from django.apps import AppConfig
from django.conf import settings

from bokeh.command.util import build_single_handler_applications
from bokeh.server.contexts import ApplicationContext
from bokeh.application.handlers.function import FunctionHandler
from bokeh.application.handlers.document_lifecycle import DocumentLifecycleHandler
from .routing import RoutingConfiguration

def is_bokeh_app(entry: os.DirEntry) -> bool:
    return entry.is_dir() or entry.name.endswith(('.py', '.ipynb'))

class DjangoBokehConfig(AppConfig):

    name = label = 'bokeh.server.django'

    def ready(self) -> None:
        apps_dir = os.path.join(settings.BASE_DIR, "bokeh_apps")

        paths = [ entry.path for entry in os.scandir(apps_dir) if is_bokeh_app(entry) ]
        apps = build_single_handler_applications(paths)

        for app in apps.values():
            if not any(isinstance(handler, DocumentLifecycleHandler) for handler in app.handlers):
                app.add(DocumentLifecycleHandler())

        io_loop = asyncio.get_event_loop()
        contexts = {url: ApplicationContext(app, io_loop=io_loop, url=url) for (url, app) in apps.items()}
        self.routes = RoutingConfiguration(contexts)

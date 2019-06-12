import json
import asyncio
import logging
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.generic.http import AsyncHttpConsumer

from bokeh.embed.server import server_html_page_for_session
from bokeh.resources import Resources
from bokeh.server.connection import ServerConnection
from bokeh.server.views.static_handler import StaticHandler
from bokeh.server.protocol_handler import ProtocolHandler
from bokeh.protocol import Protocol
from bokeh.protocol.receiver import Receiver
from bokeh.util.session_id import generate_session_id, check_session_id_signature

from tornado import locks

log = logging.getLogger(__name__)

# TODO: remove this when Python 2.x is dropped
class AsyncServerConnection(ServerConnection):

    async def send_patch_document(self, event):
        """ Sends a PATCH-DOC message, returning a Future that's completed when it's written out. """
        msg = self.protocol.create('PATCH-DOC', [event])
        await self._socket._send_bokeh_message(msg)

class BokehAppHTTPConsumer(AsyncHttpConsumer):

    def __init__(self, scope: Dict[str, Any]):
        super(BokehAppHTTPConsumer, self).__init__(scope)

        kwargs = self.scope['url_route']["kwargs"]
        self.application_context = kwargs["app_context"]

    async def _get_session(self):
        session_id = generate_session_id(secret_key=None, signed=False)
        self.arguments = {}
        session = await self.application_context.create_session_if_needed(session_id, self)
        return session

    async def handle(self, body: bytes) -> None:
        session = await self._get_session()
        resources = Resources(mode="server", root_url="/", path_versioner=StaticHandler.append_version)
        page = server_html_page_for_session(session,
                                            resources=resources,
                                            title=session.document.title,
                                            template=session.document.template,
                                            template_variables=session.document.template_variables)
        await self.send_response(200, page.encode(), headers=[(b"Content-Type", b"text/html")])

class BokehAppWebsocketConsumer(AsyncWebsocketConsumer):

    def __init__(self, scope):
        super(BokehAppWebsocketConsumer, self).__init__(scope)

        kwargs = self.scope['url_route']["kwargs"]
        self.application_context = kwargs["app_context"]
        self._clients = set()
        self.lock = locks.Lock()

    async def connect(self):
        log.info('WebSocket connection opened')

        parsed_url = urlparse("/?" + self.scope["query_string"].decode())
        qs_dict = parse_qs(parsed_url.query)
        proto_version = qs_dict.get("bokeh-protocol-version", [None])[0]
        if proto_version is None:
            self.close()
            raise Exception("No bokeh-protocol-version specified")

        session_id = qs_dict.get("bokeh-session-id", [None])[0]
        if session_id is None:
            self.close()
            raise Exception("No bokeh-session-id specified")

        if not check_session_id_signature(session_id,
                                          signed=False,
                                          secret_key=None):
            log.error("Session id had invalid signature: %r", session_id)
            raise Exception("Invalid session ID")

        def on_fully_opened(future):
            e = future.exception()
            if e is not None:
                # this isn't really an error (unless we have a
                # bug), it just means a client disconnected
                # immediately, most likely.
                log.debug("Failed to fully open connlocksection %r", e)

        future = self._async_open(session_id, proto_version)

        # rewrite above line using asyncio
        # this task is scheduled to run soon once context is back to event loop
        task = asyncio.ensure_future(future)
        task.add_done_callback(on_fully_opened)
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data) -> None:
        fragment = text_data

        message = await self.receiver.consume(fragment)
        if message:
            work = await self.handler.handle(message, self.connection)
            if work:
                await self._send_bokeh_message(work)

    async def _async_open(self, session_id, proto_version) -> None:
        try:
            self.arguments = {}
            self.request = self
            await self.application_context.create_session_if_needed(session_id, self.request)
            session = self.application_context.get_session(session_id)

            protocol = Protocol(proto_version)
            self.receiver = Receiver(protocol)
            log.debug("Receiver created for %r", protocol)

            self.handler = ProtocolHandler()
            log.debug("ProtocolHandler created for %r", protocol)

            self.connection = self._new_connection(protocol, self, self.application_context, session)
            log.info("ServerConnection created")

        except Exception as e:
            log.error("Could not create new server session, reason: %s", e)
            self.close()
            raise e

        msg = self.connection.protocol.create('ACK')
        await self._send_bokeh_message(msg)

    async def _send_bokeh_message(self, message):
        sent = 0
        try:
            async with self.lock:
                await self.send(text_data=message.header_json)
                sent += len(message.header_json)

                await self.send(text_data=message.metadata_json)
                sent += len(message.metadata_json)

                await self.send(text_data=message.content_json)
                sent += len(message.content_json)

                for header, payload in message._buffers:
                    await self.send(text_data=json.dumps(header))
                    await self.send(bytes_data=payload)
                    sent += len(header) + len(payload)
        except Exception:  # Tornado 4.x may raise StreamClosedError
            # on_close() is / will be called anyway
            log.warn("Failed sending message as connection was closed")
        return sent

    def _new_connection(self, protocol, socket, application_context, session):
        connection = AsyncServerConnection(protocol, socket, application_context, session)
        self._clients.add(connection)
        return connection

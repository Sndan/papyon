# -*- coding: utf-8 -*-
#
# pymsn - a python client library for Msn
#
# Copyright (C) 2005-2007 Ali Sabil <ali.sabil@gmail.com>
# Copyright (C) 2006-2007 Ole André Vadla Ravnås <oleavr@gmail.com>
# Copyright (C) 2007 Johann Prieur <johann.prieur@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Client
This module contains classes that clients should use in order to make use
of the library."""

import profile
import msnp

import pymsn.service.SingleSignOn as SSO
import pymsn.service.AddressBook as AB
import pymsn.service.OfflineIM as OIM
import pymsn.service.Spaces as Spaces

from transport import *
from switchboard_manager import SwitchboardManager
from msnp2p import P2PSessionManager
from p2p import MSNObjectStore
from conversation import SwitchboardConversation, ExternalNetworkConversation
from pymsn.event import ClientState, ClientErrorType, \
    AuthenticationError, EventsDispatcher

import logging

__all__ = ['Client']

logger = logging.getLogger('client')

class Client(EventsDispatcher):
    """This class provides way to connect to the notification server as well
    as methods to manage the contact list, and the personnal settings.

    Basically you should inherit from this class and implement the callbacks
    in order to build a client.

    @group Connection: login, logout"""

    def __init__(self, server, proxies={}, transport_class=DirectConnection):
        """Initializer

            @param server: the Notification server to connect to.
            @type server: tuple(host, port)

            @param proxies: proxies that we can use to connect
            @type proxies: {type: string => L{gnet.proxy.ProxyInfos}}"""
        EventsDispatcher.__init__(self)

        self.__state = ClientState.CLOSED
        self._proxies = proxies
        self._transport_class = transport_class
        self._proxies = proxies
        self._transport = transport_class(server, ServerType.NOTIFICATION,
                self._proxies)

        self._protocol = msnp.NotificationProtocol(self, self._transport,
                self._proxies)

        self._switchboard_manager = SwitchboardManager(self)
        self._switchboard_manager.register_handler(SwitchboardConversation)

        self._p2p_session_manager = P2PSessionManager(self)
        # TODO: attach the incoming-session signal
        self._msn_object_store = MSNObjectStore(self)

        self._external_conversations = {}

        self._sso = None
        self.profile = None
        self.address_book = None

        self.oim_box = None
        
        self.__die = False
        self.__setup_callbacks()

    def __setup_callbacks(self):
        self._transport.connect("connection-success", self._on_connect_success)
        self._transport.connect("connection-failure", self._on_connect_failure)
        self._transport.connect("connection-lost", self._on_disconnected)

        self._protocol.connect("notify::state",
                self._on_protocol_state_changed)
        self._protocol.connect("unmanaged-message-received",
                self._on_protocol_unmanaged_message_received)


        self._switchboard_manager.connect("handler-created",
                self._on_switchboard_handler_created)

    def __setup_addressbook_callbacks(self):
        self.address_book.connect('error', self._on_addressbook_error)

        def connect_signal(name):
            self.address_book.connect(name, self._on_addressbook_event, name)

        connect_signal("new-pending-contact")

        connect_signal("messenger-contact-added")
        connect_signal("contact-deleted")

        connect_signal("contact-blocked")
        connect_signal("contact-unblocked")

        connect_signal("group-added")
        connect_signal("group-deleted")
        connect_signal("group-renamed")
        connect_signal("group-contact-added")
        connect_signal("group-contact-deleted")

    def __setup_oim_box_callbacks(self):
        self.oim_box.connect("notify::state", 
                             self._on_oim_box_state_changed)

        self.oim_box.connect('error', self._on_oim_box_error)

        def connect_signal(name):
            self.oim_box.connect(name, self._on_oim_box_event, name)

        connect_signal("messages-received")
        connect_signal("messages-fetched")
        connect_signal("message-sent")
        connect_signal("messages-deleted")

    def _get_state(self):
        return self.__state
    def _set_state(self, state):
        self.__state = state
        self._dispatch("on_client_state_changed", state)
    state = property(_get_state)
    _state = property(_get_state, _set_state)

    ### public methods & properties
    def login(self, account, password):
        """Login to the server.

            @param account: the account to use for authentication.
            @type account: string

            @param password: the password needed to authenticate to the account
            """
        assert(self._state == ClientState.CLOSED, "Login already in progress")
        self.__die = False
        self.profile = profile.User((account, password), self._protocol)
        self._transport.establish_connection()
        self._state = ClientState.CONNECTING

    def logout(self):
        """Logout from the server."""
        if self.__state != ClientState.OPEN: # FIXME: we need something better
            return
        self.__die = True
        self._protocol.signoff()
        self._switchboard_manager.close()
        self.__state = ClientState.CLOSED

    ### External Conversation handling
    def _register_external_conversation(self, conversation):
        for contact in conversation.participants:
            break

        if contact in self._external_conversations:
            logger.warning("trying to register an external conversation twice")
            return
        self._external_conversations[contact] = conversation

    def _unregister_external_conversation(self, conversation):
        for contact in conversation.participants:
            break
        del self._external_conversations[contact]

    # - - Transport
    def _on_connect_success(self, transp):
        self._sso = SSO.SingleSignOn(self.profile.account, 
                                     self.profile.password,
                                     self._proxies)
        self.address_book = AB.AddressBook(self._sso, self._proxies)
        self.__setup_addressbook_callbacks()
        self.oim_box = OIM.OfflineMessagesBox(self._sso, self, self._proxies)
        self.__setup_oim_box_callbacks()
        self.spaces_service = Spaces.Spaces(self._sso, self._proxies)

        self._state = ClientState.CONNECTED

    def _on_connect_failure(self, transp, reason):
        self._dispatch("on_client_error", ClientErrorType.NETWORK, reason)
        self._state = ClientState.CLOSED

    def _on_disconnected(self, transp, reason):
        if not self.__die:
            self._dispatch("on_client_error", ClientErrorType.NETWORK, reason)
        self.__die = False
        self._state = ClientState.CLOSED
        
    def _on_authentication_failure(self):
        self._dispatch("on_client_error", ClientErrorType.AUTHENTICATION,
                       AuthenticationError.INVALID_USERNAME_OR_PASSWORD)
        self.__die = True
        self._transport.lose_connection()

    # - - Notification Protocol
    def _on_protocol_state_changed(self, proto, param):
        state = proto.state
        if state == msnp.ProtocolState.AUTHENTICATING:
            self._state = ClientState.AUTHENTICATING
        elif state == msnp.ProtocolState.AUTHENTICATED:
            self._state = ClientState.AUTHENTICATED
        elif state == msnp.ProtocolState.SYNCHRONIZING:
            self._state = ClientState.SYNCHRONIZING
        elif state == msnp.ProtocolState.SYNCHRONIZED:
            self._state = ClientState.SYNCHRONIZED
        elif state == msnp.ProtocolState.OPEN:
            self._state = ClientState.OPEN
            im_contacts = [contact for contact in self.address_book.contacts \
                    if contact.attributes['im_contact']]
            for contact in im_contacts:
                self._connect_contact_signals(contact)

    def _on_protocol_unmanaged_message_received(self, proto, sender, message):
        if sender in self._external_conversations:
            conversation = self._external_conversations[sender]
            conversation._on_message_received(message)
        else:
            conversation = ExternalNetworkConversation(self, [sender])
            self._register_external_conversation(conversation)
            if self._dispatch("on_invite_conversation", conversation) == 0:
                logger.warning("No event handler attached for conversations")
            conversation._on_message_received(message)

    # - - Contact
    def _connect_contact_signals(self, contact):
        contact.connect("notify::presence",
                self._on_contact_property_changed)
        contact.connect("notify::display-name",
                self._on_contact_property_changed)
        contact.connect("notify::personal-message",
                self._on_contact_property_changed)
        contact.connect("notify::current-media",
                self._on_contact_property_changed)        
        contact.connect("notify::msn-object",
                self._on_contact_property_changed)
        contact.connect("notify::client-capabilities",
                self._on_contact_property_changed)

        def connect_signal(name):
            contact.connect(name, self._on_contact_event, name)
        connect_signal("infos-changed")

    # - - Contact
    def _on_contact_property_changed(self, contact, pspec):
        method_name = "on_contact_%s_changed" % pspec.name.replace("-", "_")
        self._dispatch(method_name, contact)

    def _on_contact_event(self, contact, *args):
        event_name = args[-1]
        event_args = args[:-1]
        method_name = "on_contact_%s" % event_name.replace("-", "_")
        self._dispatch(method_name, *event_args)

    # - - Switchboard Manager
    def _on_switchboard_handler_created(self, sb_mgr, handler_class, handler):
        if handler_class is SwitchboardConversation:
            if self._dispatch("on_invite_conversation", handler) == 0:
                logger.warning("No event handler attached for conversations")
        else:
            logger.warning("Unknown Switchboard Handler class %s" % handler_class)

    # - - Address book
    def _on_addressbook_event(self, address_book, *args):
        event_name = args[-1]
        event_args = args[:-1]
        if event_name == "messenger-contact-added":
            self._connect_contact_signals(event_args[0])
        method_name = "on_addressbook_%s" % event_name.replace("-", "_")
        self._dispatch(method_name, *event_args)
            
    def _on_addressbook_error(self, address_book, error_code):
        self._dispatch("on_client_error", ClientErrorType.ADDRESSBOOK, error_code)
        self.__die = True
        self._transport.lose_connection()

    # - - Offline messages
    def _on_oim_box_state_changed(self, oim_box, pspec):
        self._dispatch("on_oim_state_changed", oim_box.state)

    def _on_oim_box_event(self, oim_box, *args):
        method_name = "on_oim_%s" % args[-1].replace("-", "_")
        self._dispatch(method_name, *args[:-1])

    def _on_oim_box_error(self, oim_box, error_code):
        self._dispatch("on_client_error", ClientErrorType.OFFLINE_MESSAGES, error_code)


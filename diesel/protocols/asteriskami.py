#
# AsteriskAMI -- Asterisk Protocol for diesel
#
# Copyright (c) 2013, Miguel Paolino
#
# Miguel Paolino <mpaolino@gmail.com>
#
# This program is free software, distributed under the terms of the
# BSD 3-Clause License. See the LICENSE file at the top of the source tree for
# details.

import diesel
from diesel import (Client, call)
from collections import deque
import uuid

import ipdb

AMI_PORT = 5038


class AMIException(Exception) : pass

class AMIError(AMIException): pass

class AMITimeout(AMIException): pass

class AMICommandError(AMIException): pass


class AsteriskAMIClient(Client):

    def __init__(self, host='localhost', port=AMI_PORT, username=None,
                 secret=None, **kw):
        if username is None:
            username = ''
        if secret is None:
            secret = ''
        self.host = host
        self.port = port
        self.username = username
        self.secret = secret
        self._events = [ 'Newchannel', 'Hangup', 'Newexten', 'Newstate',
                         'Reload', 'Shutdown', 'ExtensionsStatus', 'Rename',
                         'Newcallerid', 'Alarm', 'AlarmClear',
                         'Agentcallbacklogoff', 'Agentcallbacklogin',
                         'Agentlogin', 'Agentlogoff', 'MeetmeJoin',
                         'MeetmeLeave', 'MessageWaiting', 'Join',
                         'Leave', 'AgentCalled', 'ParkedCall',
                         'UnParkedCall', 'ParkedCalls', 'Cdr',
                         'ParkedCallsComplete', 'QueueParams',
                         'QueueMember' ]
        self._subscriptions = dict.fromkeys(self._events)
        Client.__init__(self, host, port, **kw)


    @call
    def on_connect(self):
        self.ami_version = self._get_ami_version()
        diesel.fork_child(self._dispatch_messages)
        self._do_login()
        self.on_logged_in()

    def on_logged_in(self):
        pass

    @call
    def _dispatch_messages(self):
        while True:
            # Workaround for bug in diesel that won't reschedule loop
            # when using until
            #data = diesel.until('\r\n\r\n')
            ev, data = diesel.first(sleep=0.01, until='\r\n\r\n')
            if ev == 'sleep':
                continue
            parsed = self._parse(data)
            #print(parsed)
            if 'actionid' in parsed:
                diesel.fire(parsed['actionid'], parsed)
            elif 'event' in parsed:
                event = parsed['event']
                if event in self._subscriptions and self._subscriptions[event]:
                    # Launch one fork per subscribed handler
                    for sub in self._subscriptions[event]:
                        diesel.fork_child(sub, parsed)
                else:
                    # Messages which are not recognized or
                    # doesn't have a handler are not interesting
                    # TODO: Log something?
                    print("Discarting: %s" % str(event))
                    pass

    def _parse(self, message):
        response = {}
        if message is None:
            return response

        message_lines = message.split('\r\n')
        # TODO: rewrite this to be less monkey-oriented code
        for line in message_lines:
            try:
                key, value = line.split(': ')
                response[key.lower()] = value
            except ValueError:
                pass
        return response

    @call
    def _get_ami_version(self):
        version = diesel.until_eol()
        return version

    def _do_login(self):
        '''
            Authenticate
        '''
        login_args = { 'action': 'login',
                       'username': self.username,
                       'secret': self.secret }
        response = self._send_command(login_args)
        if 'response' not in response or response['response'] != 'Success':
            raise AMICommandError(response['message'])

    def _generate_action_id(self):
        return str(uuid.uuid4())

    @call
    def _send_command(self, cmd_dict, stop_event=None, timeout=5):
        '''
            Receives a command dictionary and sends as action to Asterisk
            it will also wait and return a response 
        '''
        if not isinstance(cmd_dict, dict):
            raise AMIError('cmd_dict must be a dict type')
        if len(cmd_dict) == 0:
            raise AMIError('refusing to send empty command')

        action_id = self._generate_action_id()
        cmd_dict['actionid'] = action_id
        # Transform key:value dict to string array
        # of "key: value" elements
        cmds = map(lambda x: ''.join([x[0],': ', x[1],
                              '\r\n'] ),
                   cmd_dict.items())
        # Append last empty line and send
        cmds.append('\r\n')
        print("Sending: %s" % str(cmds))
        diesel.send(''.join(cmds))
#        sleep is scheduled and triggered even when waits is triggered
#        first. Let's workaround and just wait for the data forever.
#        TODO: find a proper way of doing this.
#        ev, response = diesel.first(sleep=timeout, waits=action_id)
#        if ev == 'sleep':
#            raise AMITimeout('AMI command timed out')
        response = diesel.wait(action_id)

        if response['response'] == 'Error':
            raise AMICommandError(response['message'])

        if stop_event is None:
            return response

        response_list = []
        while 'event' not in response or stop_event != response['event']:
            response_list.append(response)
            response = diesel.wait(action_id)
        response_list.append(response)
        return response_list

    def subscribe(self, event, handler):
        '''
            Subscribe handler to event handler list, handler will
            be called passing event dictionary as the only argument
        '''
        if not isinstance(event, (str, unicode)):
            raise AMIError('event must be a str or unicode type')

        if not callable(handler):
            raise AMIError('handler must be callable')

        if event not in self._subscriptions:
            raise AMIError('event \'%s\' not valid' % str(event))

        if self._subscriptions[event] is None:
            self._subscriptions[event] = []
        self._subscriptions[event].append(handler)


    # User API
    def absolute_timeout(self, channel, timeout):
        """ Set timeout value for the given channel (in seconds) """
        message = { 'action': 'AbsoluteTimeout',
                    'timeout': timeout,
                    'channel': channel }    
        return self._send_command(message)


    def agent_logoff(self, agent, soft):
        """ Logs off the specified agent for the queue system """
        if soft in (True, 'yes', 1):
            soft = 'true'
        else:
            soft = 'false'
        message = { 'action': 'AgentLogoff',
                    'agent': agent,
                    'soft': soft }
        return self._send_command(message)


    def agents(self):
        """ Retrieve agents information """
        message = { "action": "agents" }
        return self._send_command(message)


    def change_monitor(self, channel, filename):
        """ Change the file to which the channel is to be recorded """
        message = { 'action': 'changemonitor',
                    'channel': channel,
                    'filename': filename }
        return self._send_command(message)


    def command(self, command):
        """ Run asterisk CLI command """
        message = { 'action': 'command',
                    'command': command }
        return self._send_command(message)


    def db_del(self, family, key):
        """ Delete key value in the AstDB database """
        message = { 'action': 'dbdel',
                    'family': family,
                    'key': key }
        return self._send_command(message)


    def db_del_tree(self, family, key=None):
        """ Delete key value or key tree in the AstDB database """
        message = { 'action': 'dbdeltree',
                    'family': family }
        if key is not None:
            message['key'] = key
        return self._send_command(message)


    def db_get(self, family, key):
        """ This action retrieves a value from the AstDB database """
        message = { 'action': 'DBGet',
                    'family': family,
                    'key': key }
        try:
            response = self._send_command(message, stop_event='DBGetResponse')
        except AMICommandError:
            return None
        response = response.pop()
        if 'val' not in response:
            return None
        return response['val']


    def db_put(self, family, key, value):
        """ Sets a key value in the AstDB database """
        message = { 'action': 'dbput',
                    'family': family,
                    'key': key,
                    'val': value }
        return self._send_command(message)

    def events(self, eventmask=False):
        """ Determine whether events are generated """
        if eventmask in ('off', False, 0):
            eventmask = 'off'
        elif eventmask in ('on', True, 1):
            eventmask = 'on'
        # otherwise is likely a type-mask
        message = { 'action': 'events',
                    'eventmask': eventmask }
        return self._send_command(message)

    def extension_state(self, exten, context):
        """Get extension state

        This command reports the extension state for the given extension.
        If the extension has a hint, this will report the status of the
        device connected to the extension.

        The following are the possible extension states:

        -2    Extension removed
        -1    Extension hint not found
         0    Idle
         1    In use
         2    Busy"""
        message = { 'action': 'extensionstate',
                    'exten': exten,
                    'context': context }
        return self._send_command(message)


    def get_config(self, filename):
        """ Retrieves the data from an Asterisk configuration file """
        message = { 'action': 'getconfig',
                    'filename': filename }
        return self._send_command(message)

    def get_var(self, channel, variable):
        """ Retrieve the given variable from the channel """

        message = { 'action': 'getvar',
                    'channel': channel,
                    'variable': variable }

        response = self._send_command(message)
        if 'value' in response:
            return response['val']
        return None 
        
    def hangup(self, channel):
        """ Tell channel to hang up """
        message = { 'action': 'hangup',
                    'channel': channel }
        return self._send_command(message)

    def list_commands(self):
        """ 
        List the set of commands available

        Returns a single message with each command-name as a key
        """
        message = { 'action': 'listcommands' }
        return self._send_command(message)

    def logoff(self):
        """ Log off from the manager instance """
        message = { 'action': 'logoff' }
        response = self._send_command(message)
        if response['response'] == 'Goodbye':
            return True
        return False

    def mailbox_count(self, mailbox):
        """ Get count of messages in the given mailbox """
        message = { 'action': 'mailboxcount',
                    'mailbox': mailbox }
        return self._send_command(message)

    def mailbox_status(self, mailbox):
        """ Get status of given mailbox """
        message = { 'action': 'mailboxstatus',
                    'mailbox': mailbox }
        return self._send_command(message)

    def meetme_mute(self, meetme, usernum):
        """ Mute a user in a given meetme """
        message = { 'action': 'meetmemute',
                    'meetme': meetme,
                    'usernum': usernum }
        return self._send_command(message)

    def meetme_unmute(self, meetme, usernum):
        """ Unmute a specified user in a given meetme"""
        message = { 'action': 'meetmeunmute',
                    'meetme': meetme,
                    'usernum': usernum }
        return self._send_command(message)

    def monitor(self, channel, filename, fileformat, mix):
        """Record given channel to a file (or attempt to anyway)"""
        message = { 'action': 'monitor',
                    'channel': channel,
                    'file': filename,
                    'format': fileformat,
                    'mix': mix }
        return self._send_command(message)

    def originate(self, channel, context=None, exten=None, priority=None, 
            timeout=None, callerid=None, account=None, application=None,
            data=None, variable={}, async=False
        ):
        """Originate call to connect channel to given context/exten/priority

        channel -- the outgoing channel to which will be dialed
        context/exten/priority -- the dialplan coordinate to which to connect
            the channel (i.e. where to start the called person)
        timeout -- duration before timeout in seconds
                   (note: not Asterisk standard!)
        callerid -- callerid to display on the channel
        account -- account to which the call belongs
        application -- alternate application to Dial to use for outbound dial
        data -- data to pass to application
        variable -- variables associated to the call
        async -- make the origination asynchronous
        """
        variable = '|'.join(["%s=%s" % (x[0], x[1]) for x in variable.items()])
        message = dict([(k, v) for (k, v) in {
            'action': 'originate',
            'channel': channel,
            'context': context,
            'exten': exten,
            'priority': priority,
            'timeout': timeout,
            'callerid': callerid,
            'account': account,
            'application': application,
            'data': data,
            'variable': variable,
            'async': str(async)
        }.items() if v is not None])
        if 'timeout' in message:
            message['timeout'] = message['timeout'] * 1000
        return self._send_command(message)

    def park(self, channel, channel2, timeout):
        """ Park channel """
        message = { 'action': 'park',
                    'channel': channel,
                    'channel2': channel2,
                    'timeout': timeout }
        return self._send_command(message)

    def parked_call(self):
        """ Check for a ParkedCall event """
        message = { 'action': 'parkedcalll' }
        return self._send_command(message)

    def unparked_call(self):
        """ Check for an UnParkedCall event """
        message = { 'action': 'unparkedcall' }
        return self._send_command(message)

    def parked_calls(self):
        """ Retrieve set of parked calls """
        message = { 'action': 'parkedcalls' }
        return self._send_command(message)

    def pause_monitor(self, channel):
        """ Temporarily stop recording the channel """
        message = { 'action': 'pausemonitor',
                    'channel': channel }
        return self._send_command(message)

    def ping(self):
        """ Check to see if the manager is alive... """
        message = { 'action': 'ping' }
        response = self._send_command(message)
        return True

    def play_dtmf(self, channel, digit):
        """ Play DTMF on a given channel """
        message = { 'action': 'playdtmf',
                    'channel': channel,
                    'digit': digit }
        return self._send_command(message)

    def queue_add(self, queue, interface, penalty=0, paused=True):
        """ Add given interface to named queue """
        if paused in (True, 'true', 1):
            paused = 'true'
        else:
            paused = 'false'
        message = { 'action': 'queueadd',
                    'queue': queue,
                    'interface': interface,
                    'penalty': penalty,
                    'paused': paused }
        return self._send_command(message)

    def queue_pause(self, queue, interface, paused=True):
        if paused in (True, 'true', 1):
            paused = 'true'
        else:
            paused = 'false'
        message = { 'action': 'queuepause',
                    'queue': queue,
                    'interface': interface,
                    'paused': paused }
        return self._send_command(message)

    def queue_remove(self, queue, interface):
        """ Remove given interface from named queue """
        message = { 'action': 'queueremove',
                    'queue': queue,
                    'interface': interface }
        return self._send_command(message)

    def queues(self):
        """ Retrieve information about active queues via multiple events """
        # XXX AMI returns improperly formatted lines so this doesn't work now.
        message = { 'action': 'queues' }
        return self._send_command(message)

    def queue_status(self, queue=None, member=None):
        """ Retrieve information about active queues via multiple events """
        message = { 'action': 'queuestatus' }
        if queue is not None:
            message.update({'queue': queue})
        if member is not None:
            message.update({'member': member})
        response = self._send_command(message,
                                      stop_event='QueueStatusComplete')

    def redirect(self, channel, context, exten, priority, extrachannel=None):
        """ Transfer channel(s) to given context/exten/priority """
        message = { 'action': 'redirect',
                    'channel': channel,
                    'context': context,
                    'exten': exten,
                    'priority': priority }
        if extrachannel is not None:
            message['extrachannel'] = extrachannel
        return self._send_command(message)

    def set_cdr_userfield(self, channel, userfield, append=True):
        """ Set/add to a user field in the CDR for given channel """
        if append in (True, 'true', 1):
            append = 'true'
        else:
            append = 'false'
        message = { 'channel': channel,
                    'userfield': userField,
                    'append': append }
        return self._send_command(message)

    def set_var(self, channel, variable, value):
        """ Set channel variable to given value """
        message = { 'action': 'setvar',
                    'channel': channel,
                    'variable': variable,
                    'value': value }
        return self._send_command(message)

    def sip_peers(self):
        """ List all known sip peers """
        # TODO: this shit is not going to work, fix it
        message = { 'action': 'sippeers' }
        return self._send_command(message, stop_event='PeerlistComplete')

        try:
            response = self._send_command(message, stop_event='PeerlistComplete')
        except AMICommandError:
            return None
        func = lambda x: 'event' in x and x['event'] == 'PeerEntry'
        result = filter(func, response)
        return result



    def sip_show_peer(self, peer):
        message = { 'action': 'sipshowpeer',
                    'peer': peer }
        return self._send_command(message)


    def status(self, channel=None):
        """Retrieve status for the given (or all) channels

        The results come in via multi-event callback

        channel -- channel name or None to retrieve all channels

        returns deferred returning list of Status Events for each requested
        channel
        """
        message = { 'action': 'status' }
        if channel:
            message['channel'] = channel
        return self._send_command(message, stop_event='StatusComplete')

    def stop_monitor(self, channel):
        """Stop monitoring the given channel"""
        message = { 'action': 'monitor',
                    'channel': channel }
        return self._send_command(message)

    def unpause_monitor(self, channel):
        """Resume recording a channel"""
        message = { 'action': 'unpausemonitor',
                    'channel': channel }
        return self._send_command(message)

    def update_config(self, srcfile, dstfile, mod_reload, headers={}):
        """Update a configuration file

        headers should be a dictionary with the following keys
        Action-XXXXXX
        Cat-XXXXXX
        Var-XXXXXX
        Value-XXXXXX
        Match-XXXXXX
        """
        message = {}
        if mod_reload in (True, 'yes', 1):
            mod_reload = 'yes'
        else:
            mod_reload = 'no'
        message = { 'action': 'updateconfig',
                    'srcfilename': srcfile,
                    'dstfilename': dstfile,
                    'reload': mod_reload }
        for k, v in headers.items():
            message[k] = v
        return self._send_command(message)

    def user_event(self, event, **headers):
        """Sends an arbitrary event to the Asterisk Manager Interface."""
        message = { 'action': 'UserEvent',
                    'userevent': event }
        for i, j in headers.items():
            message[i] = j
        return self._send_command(message)

    def wait_event(self, timeout):
        """Waits for an event to occur

        After calling this action, Asterisk will send you a Success response as
        soon as another event is queued by the AMI
        """
        message = { 'action': 'WaitEvent',
                    'timeout': timeout }
        return self._send_command(message)

    def dahdi_DND_off(self, channel):
        """Toggles the DND state on the specified DAHDI channel to off"""
        messge = { 'action': 'DAHDIDNDoff',
                   'channel': channel }
        return self._send_command(message)

    def dahdi_DND_on(self, channel):
        """Toggles the DND state on the specified DAHDI channel to on"""
        messge = { 'action': 'DAHDIDNDon',
                   'channel': channel }
        return self._send_command(message)

    def dahdi_dial_offhook(self, channel, number):
        """Dial a number on a DAHDI channel while off-hook"""
        message = { 'action': 'DAHDIDialOffhook',
                    'dahdichannel': channel,
                    'number': number }
        return self._send_command(message)

    def dahdi_hangup(self, channel):
        """Hangs up the specified DAHDI channel"""
        message = { 'action': 'DAHDIHangup',
                    'dahdichannel': channel }
        return self._send_command(message)

    def dahdi_restart(self, channel):
        """Restarts the DAHDI channels, terminating any calls in progress"""
        message = { 'action': 'DAHDIRestart',
                    'dahdichannel': channel }
        return self._send_command(message)

    def dahdi_show_channels(self):
        """List all DAHDI channels"""
        message = { 'action': 'DAHDIShowChannels' }
        return self._send_command(message)

    def dahdi_transfer(self, channel):
        """Transfers DAHDI channel"""
        message = { 'action': 'DAHDITransfer',
                    'channel': channel }
        return self._send_command(message)

    def reload(self, module):
        """Reload modules"""
        message = {'action': 'Reload',
                   'module': module}
        return self.sendDeferred(message).addCallback(self.errorUnlessResponse)



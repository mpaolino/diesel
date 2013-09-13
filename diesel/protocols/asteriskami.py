import diesel
from diesel import (Client, call, until_eol, until, receive,
                    fire, send, first, fork, sleep)
import uuid

import ipdb


AMI_PORT = 5038

class AsteriskAMIError(Exception): pass

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
        norm_events = map(lambda x: x.lower(), self._events)
        self._subscriptions = dict.fromkeys(norm_events)
        Client.__init__(self, host, port, **kw)


    @call
    def on_connect(self):
        self.ami_version = self._get_ami_version()
        diesel.fork_child(self._dispatch_messages)
        self._do_login()
        self.on_logged_in()

    def on_logged_in(self):
        #ipdb.set_trace()
        pass

    @call
    def _dispatch_messages(self):
        while True:
            msg = until('\r\n\r\n')
            parsed = self._parse(msg)
            ipdb.set_trace()
            if 'actionid' in parsed:
                diesel.fire(parsed['actionid'], parsed)
            elif 'event' in parsed:
                event = parsed['event']
                if event in self._subscriptions:
                    # Launch one fork per subscribed function
                    map(diesel.fork_child, self._subscriptions[event])
                else:
                    # Messages which are not recognized or
                    # doesn't have a callback are not interesing
                    # TODO: Log something
                    pass 

    def _parse(self, message):
        message_lines = message.split('\r\n')
        response = {}
        # TODO: rewrite this
        for line in message_lines:
            try:
                key, value = line.split(': ')
                response[key.lower()] = value
            except ValueError:
                pass
        return response 

    @call
    def _get_ami_version(self):
        version = until_eol()
        return version

    def _do_login(self):
        login_cmds = { 'action': 'login',
                       'username': self.username,
                       'secret': self.secret }
        response = self._send_command(login_cmds)
        if 'response' not in response or response['response'] != 'Success' \
            or response['message'] != 'Authentication accepted':
            raise AsteriskAMIError('Authentication failed')

    def _generate_action_id(self):
        return str(uuid.uuid4())

    @call
    def _send_command(self, cmd_dict):
        '''
            Receives a command dictionary and sends as action to Asterisk
            If a timeout is given this method will wait for a response,
            raising AsteriskAMITimeout in case a response is not received
            in time.
        '''
        if not isinstance(cmd_dict, dict):
            raise AsteriskAMIError('cmd_dict must be of dict type')
        if len(cmd_dict) == 0:
            raise AsteriskAMIError('refusing to send empty command')

        action_id = self._generate_action_id()
        cmd_dict['actionid'] = action_id
        # Transform key:value dict to string array
        # of "key: value" elements
        cmds = map(lambda x: ''.join([x[0],': ', x[1],
                              '\r\n'] ),
                   cmd_dict.items())
        # Append last empty line and send
        cmds.append('\r\n')
        send(''.join(cmds))
        response = diesel.wait(action_id)
        return response 

    def subscribe(self, event, handler):
        '''
            Subscribe handler to event handler chain
        '''
        if not isinstance(event, (str, unicode)):
            raise AsteriskAMIError('event must be a str or unicode type')

        if not callable(handler):
            raise AsteriskAMIError('handler must be callable')

        event = event.lower()
        if event not in self._subscriptions:
            raise AsteriskAMIError('event \'%s\' not valid' % str(event)) 

        if self._subscriptions[event] is None:
            self._subscriptions[event] = []
        self._subscriptions[event].append(handler)

###############################################################################

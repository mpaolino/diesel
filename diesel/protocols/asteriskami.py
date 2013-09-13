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
        self._message_cache = []
        Client.__init__(self, host, port, **kw)

    @call
    def on_connect(self):
        self._get_ami_version()
        self._do_login()
        self.on_logged_in()

    def on_logged_in(self):
        pass

    @call
    def _get_ami_version(self):
        fl = until_eol()

    @call
    def _do_login(self):
        login_cmds = { 'Action': 'login',
                       'Username': self.username,
                       'Secret': self.secret }
        action_id = self.send_command(login_cmds)
        response = self._get_response(action_id)
        self.logged_in = True

    def _generate_action_id(self):
        return str(uuid.uuid4())

    @call
    def send_command(self, cmd_dict):

        if not isinstance(cmd_dict, dict):
            #TODO: raise and log error
            return
        if len(cmd_dict) == 0:
            #TODO: raise and log error
            return

        action_id = self._generate_action_id()
        cmd_dict['ActionID'] = action_id
        # Transform key:value dict to string array
        # of "key: value" elements
        cmds = map(lambda x: ''.join([x[0],': ', x[1],
                              '\r\n'] ),
                   cmd_dict.items())
        # Append last empty line and send
        cmds.append("\r\n")
        send(''.join(cmds))
        return action_id

    def _get_response(self, action_id):
        response = until("\r\n\r\n")
        response_args = response.split("\r\n")
        args = {}
        for one_arg in response_args:
            try:
                key, value = one_arg.split(": ")
                args[key] = value
            except ValueError:
                pass
        return args

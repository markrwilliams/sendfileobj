from collections import namedtuple
import os
import json
import socket
from threading import Lock
from array import array
import re

from .compat import sendmsg, recvmsg_into, SCM_RIGHTS, CMSG_SPACE


class PassagewayException(Exception):
    '''\
    Raised when a Rail can't be sent across a PassageWay.
    '''

DescribedObject = namedtuple('DescribedObject', 'description filenos')


def _ensure_only_fds(filenos, only=1):
    if len(filenos) > only:
        for fd in os.close(fd):
            raise PassagewayException('Got %d filenos but expected %d'
                                      % (len(filenos), only))


class Basket(object):
    type = None

    @property
    def identity(self):
        # bytestring!
        return self.__class__.__name__.encode('utf-8')

    def describe(self, obj):
        raise NotImplemented

    def rescribe(self, decoded, filenos):
        raise NotImplemented

    def encode(self, obj):
        raise NotImplemented

    def decode(self, encoded, filenos):
        raise NotImplemented


class JSONBasketException(Exception):
    pass


class JSONBasket(Basket):

    def encode(self, obj):
        desc, filenos = self.describe(obj)
        return json.dumps(desc), filenos

    def decode(self, encoded, filenos):
        try:
            desc = json.loads(encoded)
        except ValueError:
            raise JSONBasketException("Could not deserialize object")
        return self.rescribe(desc, filenos)


class SocketBasketException(PassagewayException):
    '''\
    Raised when a SocketBasket can't process a sent or received
    socket
    '''


class SocketBasket(JSONBasket):
    type = socket.socket

    def describe(self, sock):
        desc = {'family': sock.family, 'type': sock.type, 'proto': sock.proto}
        return DescribedObject(description=desc,
                               filenos=[sock.fileno()])

    def rescribe(self, description, filenos):
        _ensure_only_fds(filenos, only=1)
        (fd,) = filenos

        desc = description
        try:
            family, type, proto = desc['family'], desc['type'], desc['proto']
        except KeyError as e:
            raise SocketBasketException('Missing socket data %r' % e.args[0])

        # https://docs.python.org/2/library/socket.html#socket.fromfd
        # Duplicate the file descriptor fd, so close it
        sock = socket.fromfd(fd, family, type, proto)
        os.close(fd)

        return sock


class OverlappingBasketException(PassagewayException):
    '''\
    Raised when Baskets overlap by either type or identity inside a
    Basket
    '''


class DisconnectedPassageway(PassagewayException):
    pass


class Passageway(object):
    '''\
    A way to send Baskets.

    defaults: when False, don't include the default baskets
    '''
    DEFAULT_BASKETS = (SocketBasket,)
    BASKET_LOCK = Lock()
    MAX_DIGITS = 1024

    _LENGTH_RE = re.compile('(?P<length>\d+):')

    def __init__(self, baskets=(), defaults=True, maxfds=1024):
        self.baskets = []
        self._identities = {}
        self._types = {}

        if defaults:
            self.register_baskets([basket()
                                   for basket in self.DEFAULT_BASKETS])
        if baskets:
            self.register_baskets(baskets)

        self.maxfds = maxfds

    def register_baskets(self, baskets):
        with self.BASKET_LOCK:
            new_types, new_ids = {}, {}
            for basket in baskets:
                new_types[basket.type] = basket
                new_ids[basket.identity] = basket

            overlapping_types = set(self._types).intersection(set(new_types))
            overlapping_ids = set(self._identities).intersection(set(new_ids))

            if overlapping_types or overlapping_ids:
                def basket_names(baskets):
                    return ', '.join(b.__class__.__name__ for b in baskets)

                msg = ''
                if overlapping_types:
                    msg += ('Overlapped existing by type:'
                            ' %s' % basket_names(overlapping_types))
                if overlapping_ids:
                    msg += ('Overlapping existing by identity:'
                            ' %s' % basket_names(overlapping_ids))

                raise OverlappingBasketException(msg)

            self._types.update(new_types)
            self._identities.update(new_ids)

    def _send_netstring_pair(self, sock, identity, encoded, filenos):
        # TODO: transport and protocol

        # netstring
        to_send = b'%d:%s,%d:%s,' % (len(identity), identity,
                                     len(encoded), encoded)

        packed_fds = array('i', filenos)
        result = sendmsg(sock, [to_send], [(socket.SOL_SOCKET,
                                            SCM_RIGHTS,
                                            packed_fds)])
        to_send = to_send[result:]
        while to_send:
            result = sendmsg(sock, [to_send])
            to_send = to_send[result:]

    def _recv_netstring(self, sock, receive_fds=True):
        # TODO: transport and protocol -- especially: what happens if
        # sock is SOCK_STREAM and the connection is closed mid-read?
        fds = array('i')
        ancbufsize = 0
        if receive_fds:
            ancbufsize = CMSG_SPACE(self.maxfds * fds.itemsize)

        # retrieve length
        m = None
        length_buf = bytearray()
        while m is None:
            new_buf = bytearray(self.MAX_DIGITS - len(length_buf))
            recvd = recvmsg_into(sock, [new_buf], ancbufsize=ancbufsize,
                                 flags=socket.MSG_PEEK)
            nbytes, ancdata, msg_flag, address = recvd

            for cmsg_level, cmsg_type, cmsg_data in ancdata:
                if (cmsg_level, cmsg_type) == (socket.SOL_SOCKET,
                                               SCM_RIGHTS):
                    cmsg_data = str(cmsg_data)
                    fds.fromstring(cmsg_data[:len(cmsg_data)
                                             - (len(cmsg_data)
                                                % fds.itemsize)])

            if not nbytes:
                raise DisconnectedPassageway

            length_buf += new_buf[:nbytes]

            m = self._LENGTH_RE.match(length_buf)
            if not m and len(length_buf) >= self.MAX_DIGITS:
                raise PassagewayException('Could not read length of'
                                          ' bucket message')

        consumed_length = sock.recv(m.end())
        assert consumed_length == m.group()
        length = int(m.group('length')) + 1  # including ,

        data_read = 0
        data_chunks = []
        while data_read < length:
            chunk = sock.recv(length - data_read)
            data_read += len(chunk)

            if not chunk:
                raise DisconnectedPassageway

            data_chunks.append(chunk)

        data = ''.join(data_chunks)

        if not data[-1] == ',':
            raise PassagewayException('Unexpected terminating char '
                                      '%r' % data[-1])

        return data[:-1], list(fds)

    def transfer(self, sock, obj):
        # TODO: do we honor inheritance?
        with self.BASKET_LOCK:
            basket = self._types.get(type(obj))

        if basket is None:
            raise PassagewayException("Don't have a basket for type"
                                      ' of %r' % obj)

        encoded, filenos = basket.encode(obj)
        self._send_netstring_pair(sock,
                                  identity=basket.identity,
                                  encoded=encoded,
                                  filenos=filenos)

    def obtain(self, sock, obj_type):
        with self.BASKET_LOCK:
            basket = self._types.get(obj_type)

        if basket is None:
            raise PassagewayException("Can't obtain "
                                      'object of type %r' % obj_type)

        identity, filenos = self._recv_netstring(sock, receive_fds=True)
        if basket.identity != identity:
            raise PassagewayException('Unexpected identity %s' % identity)
        encoded, _ = self._recv_netstring(sock)
        return basket.decode(str(encoded), filenos)

from collections import namedtuple
import ctypes
import os
import socket

socklen_t = ctypes.c_uint
SCM_RIGHTS = 0x01
libc = ctypes.CDLL('libc.so.6', use_errno=True)


class iovec(ctypes.Structure):
    _fields_ = [('iov_base', ctypes.c_void_p),
                ('iov_len', ctypes.c_size_t)]


iovec_ptr = ctypes.POINTER(iovec)


class cmsghdr(ctypes.Structure):
    _fields_ = [('cmsg_len', ctypes.c_size_t),
                ('cmsg_level', ctypes.c_int),
                ('cmsg_type', ctypes.c_int)]

    # fake a flexarray
    @classmethod
    def with_data(cls, cmsg_len, cmsg_level, cmsg_type, cmsg_data):
        FlexArray = ctypes.c_ubyte * ctypes.sizeof(cmsg_data)

        class _cmsghdr(ctypes.Structure):
            _fields_ = cls._fields_ + [('cmsg_data', FlexArray)]

        as_bytes = FlexArray(*map(ord, buffer(cmsg_data)))
        return _cmsghdr(cmsg_len=cmsg_len,
                        cmsg_level=cmsg_level,
                        cmsg_type=cmsg_type,
                        cmsg_data=as_bytes)


class msghdr(ctypes.Structure):
    _fields_ = [('msg_name', ctypes.c_void_p),
                ('msg_namelen', socklen_t),
                ('msg_iov', iovec_ptr),
                ('msg_iovlen', ctypes.c_size_t),
                ('msg_control', ctypes.c_void_p),
                ('msg_controllen', ctypes.c_size_t),
                ('msg_flag', ctypes.c_int)]


def CMSG_ALIGN(length):
    sizeof_size_t = ctypes.sizeof(ctypes.c_size_t)
    return ctypes.c_size_t((length + sizeof_size_t - 1)
                           & ~(sizeof_size_t - 1))


def CMSG_SPACE(length):
    length_align = CMSG_ALIGN(length).value
    sizeof_cmsghdr = ctypes.sizeof(cmsghdr)
    cmsghdr_align = CMSG_ALIGN(sizeof_cmsghdr).value
    return ctypes.c_size_t(length_align + cmsghdr_align)


def CMSG_LEN(length):
    sizeof_cmshdr = ctypes.sizeof(cmsghdr)
    return ctypes.c_size_t(CMSG_ALIGN(sizeof_cmshdr).value + length)


_sendmsg = libc.sendmsg
_sendmsg.argtypes = [ctypes.c_int,
                     ctypes.POINTER(msghdr),
                     ctypes.c_int]
_sendmsg.restype = ctypes.c_int

_recvmsg = libc.recvmsg
_recvmsg.argtypes = [ctypes.c_int,
                     ctypes.POINTER(msghdr),
                     ctypes.c_int]
_recvmsg.restype = ctypes.c_int


class FileDescriptorType(namedtuple('FileDescriptorType', 'type data')):

    IS_FILE = '\x01'
    IS_SOCKET = '\x02'

    # <= glib 2.14 only parses up to 6 mode chars; > parses 7
    # so 1 byte for type + 7 bytes for mode + 1 byte for \00
    SIZE = 1 + 7 + 1

    def __new__(cls, type, data):
        if type not in (cls.IS_FILE, cls.IS_SOCKET):
            raise ValueError('Unknown type {0}'.format(cls.type))
        return super(FileDescriptorType, cls).__new__(cls, type, data)

    @property
    def packed(self):
        to_pack = self.type + self.data
        buf = self.create_buffer()
        assert len(to_pack) < len(buf)
        buf.value = to_pack
        return buf

    def fileobj(self, fd):
        if self.type == self.IS_FILE:
            return os.fdopen(fd, self.data)
        elif self.type == self.IS_SOCKET:
            family, type, proto = self.data
            return socket.fromfd(fd, int(family), int(type), int(proto))
        else:
            raise ValueError('Unknown type {0}'.format(self.type))

    @classmethod
    def create_buffer(cls):
        # create_string_buffer adds a null byte for you
        return ctypes.create_string_buffer('\x00' * (cls.SIZE - 1))

    @classmethod
    def frompacked(cls, packed):
        assert len(packed) <= cls.SIZE
        value = packed.value
        return cls(value[0], value[1:])

    @classmethod
    def fromfileobj(cls, fileobj):
        if isinstance(fileobj, file):
            fd_type = cls.IS_FILE
            data = fileobj.mode[:7]
        elif isinstance(fileobj, socket.socket):
            fd_type = cls.IS_SOCKET
            data = '{0}{1}{2}'.format(fileobj.family,
                                      fileobj.type,
                                      fileobj.proto)
        else:
            raise ValueError("Can't send file object of {0}".format(fileobj))

        return cls(fd_type, data)

    def __repr__(self):
        cn = self.__class__.__name__
        type = 'IS_SOCKET' if self.type == self.IS_SOCKET else 'IS_FILE'
        return '{0}(type={1}, data={2!r})'.format(cn, type, self.data)


def msghdr_for_fd(fd, fd_type=None):
    """Create an SCM_RIGHTS message header containing `fd' in its control
    message and optionally `data' (an instance of some ctypes
    class) inside its io vector.
    """
    if fd_type is None:
        fd_type_buf = FileDescriptorType.create_buffer()
    else:
        fd_type_buf = fd_type.packed

    iov = iovec(iov_base=ctypes.addressof(fd_type_buf),
                iov_len=ctypes.c_size_t(ctypes.sizeof(fd_type_buf)))

    cfd = ctypes.c_int(fd)

    cmhp = cmsghdr.with_data(cmsg_len=CMSG_LEN(ctypes.sizeof(cfd)),
                             cmsg_level=socket.SOL_SOCKET,
                             cmsg_type=SCM_RIGHTS,
                             cmsg_data=cfd)

    mh = msghdr(msg_name=None,
                msg_namelen=0,
                msg_iov=iovec_ptr(iov),
                msg_iovlen=1,
                msg_control=ctypes.addressof(cmhp),
                msg_controllen=ctypes.c_size_t(ctypes.sizeof(cmhp)))

    # save references to these so they don't get deleted!
    mh.cmsg = cmhp
    mh.iovec = iov
    mh.fd_type_buf = fd_type_buf
    return mh


class CMSGError(socket.error):
    pass


def sendfileobj(sock, fileobj):
    fd_type = FileDescriptorType.fromfileobj(fileobj)
    mh = msghdr_for_fd(fileobj.fileno(), fd_type=fd_type)
    if _sendmsg(ctypes.c_int(sock.fileno()), mh, 0) == -1:
        errno = ctypes.get_errno()
        raise CMSGError(errno,
                        'Could not send message: ' + os.strerror(errno))


def recvfileobj(sock):
    mh = msghdr_for_fd(0)
    res = _recvmsg(ctypes.c_int(sock.fileno()), mh, 0)
    if res == -1:
        errno = ctypes.get_errno()
        raise CMSGError(errno,
                        'Could not receive message: ' + os.strerror(errno))
    elif res != FileDescriptorType.SIZE:
        raise CMSGError(-1, 'Received message too small')

    # equivalent to CMSG_DATA pointer
    cmsg_data_ptr = ctypes.cast(mh.cmsg.cmsg_data,
                                ctypes.POINTER(ctypes.c_int))

    fd = cmsg_data_ptr.contents.value
    fd_type = FileDescriptorType.frompacked(mh.fd_type_buf)
    return fd_type.fileobj(fd)

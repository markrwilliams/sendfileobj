from errno import errorcode
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
    CMSG_DATA_TYPE = ctypes.c_ubyte

    # fake a flexarray
    @classmethod
    def with_data(cls, cmsg_len, cmsg_level, cmsg_type, cmsg_data):
        FlexArray = cls.CMSG_DATA_TYPE * ctypes.sizeof(cmsg_data)

        class _cmsghdr(ctypes.Structure):
            _fields_ = cls._fields_ + [('cmsg_data', FlexArray)]

        return _cmsghdr(cmsg_len=cmsg_len,
                        cmsg_level=cmsg_level,
                        cmsg_type=cmsg_type,
                        cmsg_data=cmsg_data)


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
    return ctypes.c_size_t(length_align + cmsghdr_align).value


def CMSG_LEN(length):
    sizeof_cmshdr = ctypes.sizeof(cmsghdr)
    return ctypes.c_size_t(CMSG_ALIGN(sizeof_cmshdr).value
                           + length)


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


class CMSGError(socket.error):

    def __init__(self, errno, msg):
        name = errorcode[errno]
        msg = '(%s) %s: %s' % (name, msg, os.strerror(errno))
        super(CMSGError, self).__init__(errno, msg)


ControlMessageHeader = namedtuple('ControlMessageHeader', 'level type data')


def create_iovs(buffers, writable=False):
    creation_method = 'from_buffer' if writable else 'from_buffer_copy'
    iovs = []
    for buf in buffers:
        ArrayType = ctypes.c_ubyte * len(buf)
        array = getattr(ArrayType, creation_method)(buf)
        iovs.append(iovec(iov_base=ctypes.cast(array, ctypes.c_void_p),
                          iov_len=ctypes.c_size_t(len(buf))))
    return iovs


def create_cmsghdr(cmsg_level, cmsg_type, raw_data, writable=False):
    creation_method = 'from_buffer' if writable else 'from_buffer_copy'
    CMSGDataType = (cmsghdr.CMSG_DATA_TYPE * len(buffer(raw_data)))
    cmsg_data = getattr(CMSGDataType, creation_method)(raw_data)

    return cmsghdr.with_data(cmsg_len=CMSG_LEN(ctypes.sizeof(cmsg_data)),
                             cmsg_level=cmsg_level,
                             cmsg_type=cmsg_type,
                             cmsg_data=cmsg_data)


def pack_cmsghdrs(cmsg_headers):
    if not cmsg_headers:
        return None, 0
    msg_control_bytes = ''.join(buffer(cmh)[:] for cmh in cmsg_headers)
    msg_control_buffer = (ctypes.c_char
                          * len(msg_control_bytes))(*msg_control_bytes)
    msg_control = ctypes.cast(msg_control_buffer, ctypes.c_void_p)
    # stash a reference here to avoid garbage collection
    msg_control._msg_control_bytes = msg_control_bytes
    msg_control._msg_control_buffer = msg_control_buffer
    msg_controllen = ctypes.c_size_t(len(msg_control_buffer))
    return msg_control, msg_controllen


c_ubyte_p = ctypes.POINTER(ctypes.c_ubyte)


def unpack_cmsghdrs(msg_control, msg_controllen):
    complete_header = ctypes.cast(msg_control,
                                  c_ubyte_p)[:msg_controllen]
    header_length = CMSG_LEN(0).value
    buf = bytearray(complete_header)
    offset = 0

    cmsg_headers = []
    while offset < msg_controllen:
        cmsg_header = cmsghdr.from_buffer(buf, offset)
        cmsg_level = cmsg_header.cmsg_level
        cmsg_type = cmsg_header.cmsg_type
        cmsg_data = buf[offset + header_length:offset + cmsg_header.cmsg_len]
        cmsg_headers.append(ControlMessageHeader(cmsg_level,
                                                 cmsg_type,
                                                 cmsg_data))
        offset += CMSG_SPACE(cmsg_header.cmsg_len - header_length)
    return cmsg_headers


def sendmsg(sock, buffers, ancdata=(), flags=0, address=None):
    iovs = create_iovs(buffers)
    cmsg_headers = [create_cmsghdr(*datum) for datum in ancdata]
    msg_control, msg_controllen = pack_cmsghdrs(cmsg_headers)
    mh = msghdr(msg_name=None,
                msg_namelen=0,
                msg_iov=iovec_ptr((iovec * len(iovs))(*iovs)),
                msg_iovlen=len(iovs),
                msg_control=msg_control,
                msg_controllen=msg_controllen)
    result = _sendmsg(ctypes.c_int(sock.fileno()), mh, flags)
    if result == -1:
        errno = ctypes.get_errno()
        raise CMSGError(errno, 'Could not send message')
    return result


ReceivedIntoMessage = namedtuple('ReceivedIntoMessage',
                                 'nbytes ancdata flags address')


def recvmsg_into(sock, buffers, ancbufsize=0, flags=0):
    iovs = create_iovs(buffers, writable=True)
    msg_control = None
    if ancbufsize:
        msg_control = ctypes.cast((ctypes.c_ubyte * ancbufsize)(),
                                  ctypes.c_void_p)
    mh = msghdr(msg_name=None,
                msg_namelen=0,
                msg_iov=iovec_ptr((iovec * len(iovs))(*iovs)),
                msg_iovlen=len(iovs),
                msg_control=msg_control,
                msg_controllen=ancbufsize)
    nbytes = _recvmsg(ctypes.c_int(sock.fileno()), mh, flags)
    if nbytes == -1:
        errno = ctypes.get_errno()
        raise CMSGError(errno, 'Could not receive message')
    ancdata = []
    if mh.msg_controllen > 0:
        ancdata = unpack_cmsghdrs(mh.msg_control, mh.msg_controllen)
    return ReceivedIntoMessage(nbytes, ancdata, mh.msg_flag, None)

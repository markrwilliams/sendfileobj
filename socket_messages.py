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
    return ctypes.c_size_t(length_align + cmsghdr_align)


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


def msghdr_for_fd(fd, fd_buf):
    iov = iovec(iov_base=ctypes.addressof(fd_buf),
                iov_len=ctypes.c_size_t(ctypes.sizeof(fd_buf)))

    cmsg_data = (ctypes.c_ubyte * ctypes.sizeof(ctypes.c_int))()
    cmhp = cmsghdr.with_data(cmsg_len=CMSG_LEN(ctypes.sizeof(cmsg_data)),
                             cmsg_level=0,
                             cmsg_type=0,
                             cmsg_data=cmsg_data)

    mh = msghdr(msg_name=None,
                msg_namelen=0,
                msg_iov=iovec_ptr(iov),
                msg_iovlen=1,
                msg_control=ctypes.addressof(cmhp),
                msg_controllen=ctypes.c_size_t(ctypes.sizeof(cmhp)))

    # save references to these so they don't get deleted!
    mh.cmsg = cmhp
    mh.iovec = iov
    mh.fd_buf = fd_buf
    mh.cmsg_data = cmsg_data
    return mh


class CMSGError(socket.error):

    def __init__(self, errno, msg):
        name = errorcode[11]
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
    CMSGDataType = (cmsghdr.CMSG_DATA_TYPE * len(raw_data))
    cmsg_data = getattr(CMSGDataType, creation_method)(raw_data)

    return cmsghdr.with_data(cmsg_len=CMSG_LEN(ctypes.sizeof(cmsg_data)),
                             cmsg_level=cmsg_level,
                             cmsg_type=cmsg_type,
                             cmsg_data=cmsg_data)


def pack_cmsghdrs(cmsg_headers):
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
    complete_header_length = msg_controllen.value
    complete_header = ctypes.cast(msg_control,
                                  c_ubyte_p)[:complete_header_length]
    header_length = CMSG_LEN(0).value
    buf = bytearray(complete_header)
    offset = 0
    while offset < complete_header_length:
        cmsg_header = cmsghdr.from_buffer(buf, offset)
        cmsg_level = cmsg_header.cmsg_level
        cmsg_type = cmsg_header.cmsg_type
        cmsg_data = buf[offset + header_length:offset + cmsg_header.cmsg_len]
        yield ControlMessageHeader(cmsg_level, cmsg_type, cmsg_data)
        offset += CMSG_SPACE(cmsg_header.cmsg_len - header_length).value


def sendmsg(sock, buffers, ancdata=(), flags=0):
    iovs = []
    for buf in buffers:
        array = (ctypes.c_byte * len(buf)).from_buffer_copy(buffer(buf))
        iovs.append(iovec(iov_base=ctypes.cast(array, ctypes.c_void_p),
                          iov_len=ctypes.c_size_t(len(buf))))

    cmhs = []
    for datum in ancdata:
        cmsg_level, cmsg_type, raw_data = datum
        raw_data = buffer(raw_data)
        cmsg_data = (cmsghdr.CMSG_DATA_TYPE
                     * len(raw_data)).from_buffer_copy(raw_data)
        cmh = cmsghdr.with_data(cmsg_len=CMSG_LEN(len(raw_data)),
                                cmsg_level=cmsg_level,
                                cmsg_type=cmsg_type,
                                cmsg_data=cmsg_data)
        cmhs.append(cmh)

    # the flexarrays at the end of the struct break ctype's arrays, so
    # we have to do this by hand
    msg_control_bytes = ''.join(buffer(cmh)[:] for cmh in cmhs)
    msg_control_buffer = (ctypes.c_char
                          * len(msg_control_bytes))(*msg_control_bytes)
    msg_control = ctypes.cast(msg_control_buffer, ctypes.c_void_p)
    msg_controllen = ctypes.c_size_t(len(msg_control_buffer))
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


def recvmsg_into(sock, buffers, ancbufsize=None, flags=0):
    pass


def recvfileobj(sock):
    mh = msghdr_for_fd(0, fd_buf=ctypes.create_string_buffer('\x00' * 5))
    res = _recvmsg(ctypes.c_int(sock.fileno()), mh, 0)
    if res == -1:
        errno = ctypes.get_errno()
        raise CMSGError(errno, 'Could not receive message')

    # equivalent to CMSG_DATA pointer
    import pdb; pdb.set_trace()
    cmsg_data_ptr = ctypes.cast(mh.cmsg.cmsg_data,
                                ctypes.POINTER(ctypes.c_int))
    return cmsg_data_ptr.contents.value, mh.fd_buf.value

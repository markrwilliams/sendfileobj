import socket

recvmsg_into = getattr(socket.socket, 'recvmsg_into', None)
sendmsg = getattr(socket.socket, 'sendmsg', None)
SCM_RIGHTS = getattr(socket, 'SCM_RIGHTS', None)
CMSG_SPACE = getattr(socket, 'SCM_RIGHTS', None)


if not all([callable(recvmsg_into), callable(sendmsg)]):
    from _ctypes_socket import (recvmsg_into, sendmsg, SCM_RIGHTS,
                                CMSG_SPACE)

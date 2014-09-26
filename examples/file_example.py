import argparse
import os
import socket
import array
import socket_messages as S

argparser = argparse.ArgumentParser(description='an example of sendfileobj')
argparser.add_argument('socket_path')
argparser.add_argument('--send', '-s',
                       nargs='+',
                       help='path to the file to open and send')


if __name__ == '__main__':
    args = argparser.parse_args()

    if args.send:
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.connect(args.socket_path)

        files = map(open, args.send)
        fds = array.array('i', map(file.fileno, files))

        S.sendmsg(unix_domain_socket,
                  ["hello"],
                  [S.ControlMessageHeader(socket.SOL_SOCKET,
                                          S.SCM_RIGHTS,
                                          fds)])
    else:
        if os.path.exists(args.socket_path):
            os.unlink(args.socket_path)
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.bind(args.socket_path)
        unix_domain_socket.listen(1)
        connection, _ = unix_domain_socket.accept()
        buffers = [bytearray(5)]
        fds = array.array('i')

        rmsg = S.recvmsg_into(connection,
                              buffers,
                              ancbufsize=S.CMSG_SPACE(1024 *
                                                      fds.itemsize).value)
        for cmsgh in rmsg.ancdata:
            if (cmsgh.level, cmsgh.type) == (socket.SOL_SOCKET, S.SCM_RIGHTS):
                fds.fromstring(str(cmsgh.data))
        for fd in fds:
            print repr(os.fdopen(fd, 'r').read())

import argparse
import os
import socket
import sendfileobj

argparser = argparse.ArgumentParser(description='an example of sendfileobj')
argparser.add_argument('socket_path')
argparser.add_argument('--send', '-s',
                       help='path to the file to open and send')


if __name__ == '__main__':
    args = argparser.parse_args()

    if args.send:
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.connect(args.socket_path)
        sendfileobj.sendfileobj(unix_domain_socket, open(args.send))
    else:
        if os.path.exists(args.socket_path):
            os.unlink(args.socket_path)
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.bind(args.socket_path)
        unix_domain_socket.listen(1)
        connection, _ = unix_domain_socket.accept()
        recvd = sendfileobj.recvfileobj(connection)
        print repr(recvd)
        print recvd.read()

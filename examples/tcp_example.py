import argparse
import os
import socket
import sendfileobj

argparser = argparse.ArgumentParser(description='an example of sendfileobj')
argparser.add_argument('socket_path', metavar='socket path')
argparser.add_argument('--send', '-s',
                       help='domain to connect to')


if __name__ == '__main__':
    args = argparser.parse_args()

    if args.send:
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.connect(args.socket_path)

        http = socket.create_connection((args.send, '80'))
        http.sendall('GET / HTTP/1.0\r\n'
                     '\r\n')

        sendfileobj.sendfileobj(unix_domain_socket, http)
    else:
        if os.path.exists(args.socket_path):
            os.unlink(args.socket_path)
        unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        unix_domain_socket.bind(args.socket_path)
        unix_domain_socket.listen(1)
        connection, _ = unix_domain_socket.accept()

        recvd = sendfileobj.recvfileobj(connection)

        print repr(recvd)
        print recvd.recv(1024)

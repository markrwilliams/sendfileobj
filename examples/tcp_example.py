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
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(args.socket_path)

        conn = socket.create_connection((args.send, '80'))
        conn.sendall('GET / HTTP/1.0\r\n'
                     '\r\n')

        sendfileobj.sendfileobj(sock, conn)
    else:
        if os.path.exists(args.socket_path):
            os.unlink(args.socket_path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(args.socket_path)
        sock.listen(1)
        connection, _ = sock.accept()

        recvd = sendfileobj.recvfileobj(connection)

        print repr(recvd)
        print recvd.recv(1024)

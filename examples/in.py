import socket
from passage.way import Passageway
from passage.connections import connect

outbound = connect('/tmp/socket')

pw = Passageway()


while True:
    sock = pw.obtain(outbound, socket.socket)
    print sock, len(sock.recv(1024))
    sock.close()

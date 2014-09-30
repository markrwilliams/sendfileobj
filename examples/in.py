import socket
from passage.way import Passageway
from passage.connections import bind

listener = bind('/tmp/socket')
pw = Passageway()
inbound, _ = listener.accept()


while True:
    sock = pw.obtain(inbound, socket.socket)
    print sock, len(sock.recv(1024))
    sock.close()

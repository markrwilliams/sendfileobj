import socket
from passage.way import Passageway
from passage.connections import bind

listener = bind('/tmp/socket')
inbound, _ = listener.accept()

pw = Passageway()


while True:
    sock = socket.create_connection(('localhost', 8080))
    sock.sendall('GET / HTTP/1.0\r\n\r\n')
    pw.transfer(inbound, sock)
    sock.close()

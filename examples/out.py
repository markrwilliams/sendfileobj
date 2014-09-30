import socket
from passage.way import Passageway
from passage.connections import connect
import time


outbound = connect('/tmp/socket')

pw = Passageway()


while True:
    sock = socket.create_connection(('localhost', 8080))
    sock.sendall('GET / HTTP/1.0\r\n\r\n')
    pw.transfer(outbound, sock)
    sock.close()

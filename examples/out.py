import socket
from passage.way import Passageway
from passage.connections import connect


sock = socket.create_connection(('www.google.com', 80))
sock.sendall('GET / HTTP/1.0\r\n\r\n')

Passageway().transfer(connect('/tmp/socket'), sock)

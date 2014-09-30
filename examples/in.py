import socket
from passage.way import Passageway
from passage.connections import bind

print Passageway().obtain(bind('/tmp/socket'), socket.socket).recv(1024)

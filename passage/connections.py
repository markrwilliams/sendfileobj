import os
import socket


def bind(path):
    if os.path.exists(path):
        os.unlink(path)
    unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    unix_domain_socket.bind(path)
    return unix_domain_socket


def connect(path):
    unix_domain_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    unix_domain_socket.connect(path)
    return unix_domain_socket

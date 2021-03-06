import pytest
import os
import socket
from sendfileobj import FileDescriptorType


def test_FileDescriptorType():
    buf = FileDescriptorType.create_buffer()
    assert len(buf) == FileDescriptorType.SIZE
    assert bytearray(buf) == '\x00' * FileDescriptorType.BYTESIZE

    fdt = FileDescriptorType(FileDescriptorType.IS_FILE, 'r')

    repr(fdt)

    data = bytearray([FileDescriptorType.IS_FILE]) + bytearray('r')
    buf = FileDescriptorType.create_buffer(data)

    # list for ease of reading pytest asserts
    assert list(fdt.packed) == list(buf)

    assert FileDescriptorType.frompacked(buf) == fdt

    with open('/dev/zero', 'r+') as f:
        file_fdt = FileDescriptorType.fromfileobj(f)
        assert file_fdt.type == FileDescriptorType.IS_FILE
        assert file_fdt.data == 'r+'

    fd = os.open('/dev/zero', os.O_RDWR)
    reconstructed_file = file_fdt.fileobj(fd)
    assert reconstructed_file.read(1) == '\x00'

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    sock_fdt = FileDescriptorType.fromfileobj(sock)

    assert sock_fdt.type == FileDescriptorType.IS_SOCKET
    assert sock_fdt.data == (1, 2, 0)

    data = bytearray([FileDescriptorType.IS_SOCKET]) + bytearray((1, 2, 0))
    buf = FileDescriptorType.create_buffer(data)

    assert list(sock_fdt.packed) == list(buf)

    reconstructed_sock = sock_fdt.fileobj(sock.fileno())
    assert reconstructed_sock.family == sock.family
    assert reconstructed_sock.type == sock.type
    assert reconstructed_sock.proto == sock.proto

    with pytest.raises(ValueError):
        FileDescriptorType(123444, 'sdfsdf')

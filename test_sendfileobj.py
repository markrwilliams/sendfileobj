import pytest
import os
import socket
from sendfileobj import FileDescriptorType


def test_FileDescriptorType():
    buf = FileDescriptorType.create_buffer()
    assert len(buf) == FileDescriptorType.SIZE
    assert buf.raw == '\x00' * FileDescriptorType.SIZE

    fdt = FileDescriptorType(FileDescriptorType.IS_FILE, 'r')

    repr(fdt)

    buf = FileDescriptorType.create_buffer()
    buf.value = FileDescriptorType.IS_FILE + 'r'

    assert fdt.packed.raw == buf.raw

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
    assert sock_fdt.data == '120'

    buf = FileDescriptorType.create_buffer()
    buf.value = FileDescriptorType.IS_SOCKET + '120'

    assert sock_fdt.packed.raw == buf.raw

    reconstructed_sock = sock_fdt.fileobj(sock.fileno())
    assert reconstructed_sock.family == sock.family
    assert reconstructed_sock.type == sock.type
    assert reconstructed_sock.proto == sock.proto

    with pytest.raises(ValueError):
        FileDescriptorType(123444, 'sdfsdf')

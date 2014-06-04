`sendfileobj`
===========

What
----

`sendfileobj` lets you send file-like objects that implement `.fileno()` across a Unix domain socket.

It hopes to do so for Python 2 and 3 on Linux, BSD, Mac OS X and Windows.

Why
---

There are several ways to do this already:

1. Using [https://twistedmatrix.com](Twisted)'s Unix socket transport,
   accessible via the relevant
   [http://twistedmatrix.com/documents/current/api/twisted.internet.interfaces.IReactorUNIX.html](reactor
   methods).  Twisted supports both [sending](http://twistedmatrix.com/documents/current/_downloads/sendfd.py) file descriptors and [receiving](http://twistedmatrix.com/documents/current/_downloads/recvfd.py) them.
2. Using Twisted's
   [sendmsg bindings.](http://twistedmatrix.com/documents/current/core/howto/sendmsg.html).
3. Using Libor Michalek's
   [sendmsg](https://pypi.python.org/pypi/sendmsg/1.0.1), which
   appears to expose an API that's very similar to #2.

`sendfileobj` is different because

1. It accepts a "file object" and attempts to send along enough
   information with the object's file descriptor so that it can be
   reconstructed on the receiving end.
2. It doesn't require any compilation.

How
---

Here's the interesting part of [the TCP example](examples/tcp_example.py):

````
>>> http = socket.create_connection(('github.com', '80'))
>>> http.sendall('GET / HTTP/1.0\r\n'
                 '\r\n')

>>> sendfileobj.sendfileobj(unix_domain_socket, http)
````

Then in a completely separate process:

````
>>> connection, _ = unix_domain_socket.accept()

>>> recvd = sendfileobj.recvfileobj(connection)
>>> recvd
<socket object, fd=8, family=2, type=1, protocol=6>
>>> print recvd.recv(1024)
HTTP/1.1 301 Moved Permanently
Content-length: 0
Location: https:///
Connection: close
````


Limitations
-----------

1. It only supports Python 2.  Pythons >= 3.3 will be supported via
   their native
   [sendmsg](https://docs.python.org/3/library/socket.html#socket.socket.sendmsg)
   and
   [recvmsg](https://docs.python.org/3/library/socket.html#socket.socket.recvmsg)
   functions.
2. It's currently `ctypes` based...
2. ...and it's only been tested on a relatively recent version of
   Linux (check out the `CDLL` at the top of the module)

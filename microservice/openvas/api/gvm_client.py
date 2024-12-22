from pygvm.exceptions import AuthenticationError
from pygvm.pygvm import Pygvm
from gvm.connections import UnixSocketConnection, TLSConnection
from gvm.protocols.latest import Gmp
from gvm.transforms import EtreeTransform
from pygvm.pygvm import Pygvm
import os

unixsockpath = os.getenv("UNIX_SOCK_PATH", "/run/gvmd/gvmd.sock")
gvm_type = os.getenv("GVM_TYPE", "unix")
tls_capath = os.getenv("TLS_CAPATH", "/var/lib/gvm/CA/cacert.pem")
tls_certpath = os.getenv("TLS_CERTPATH", "/var/lib/gvm/CA/clientcert.pem")
tls_keypath = os.getenv("TLS_KEYPATH", "/var/lib/gvm/private/CA/clientkey.pem")
gvmd_host = os.getenv("GVMD_HOST", "127.0.0.1")
gvmd_port = os.getenv("GVMD_PORT", "9394")
username = os.getenv("USERNAME", "admin")
password = os.getenv("PASSWORD", "cstcloud")

def get_gvm_conn() -> Pygvm:
    connection = None
    if gvm_type == "unix":
        unixsockpath = unixsockpath
        connection = UnixSocketConnection(path=unixsockpath)
    elif gvm_type == "tls":
        capath = tls_capath
        certpath = tls_certpath
        keypath = tls_keypath
        connection = TLSConnection(hostname=gvmd_host, 
                                    port=gvmd_port, 
                                    cafile=capath,
                                    certfile=certpath,
                                    keyfile=keypath)
    transform = EtreeTransform()
    gmp = Gmp(connection, transform=transform)
    pyg = Pygvm(gmp=gmp, username=username, passwd=password)
    if pyg.checkauth() is False:
        raise AuthenticationError()
    return pyg

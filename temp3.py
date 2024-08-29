from multiprocessing.connection import Client

address = "/var/folders/vz/xwxqzqx153qcxljp_4sb9shw0000gn/T/pymp-0hufqxa7/listener-l6126c4y"
# address = ("localhost", 50000)
authkey = b"password"
conn = Client(address, authkey=authkey)

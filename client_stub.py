import socket
import struct
import json
import threading
import queue


class RpcTimeoutError(Exception):
    """Raised when the server does not reply within the per-call timeout."""

class RpcError(Exception):
    """Raised when the server returns a non-null error field."""


class ParkingClient:
    def __init__(self, host="127.0.0.1", port=9001, timeout=5.0, on_event=None):
        self._host    = host
        self._port    = port
        self._timeout = timeout
        self.on_event = on_event

        self._next_id  = 0
        self._id_lock  = threading.Lock()

        self._reply_queue = queue.Queue()

        self._sock = socket.create_connection((host, port))

        self._recv_thread = threading.Thread(
            target=self._recv_loop,
            daemon=True,
            name="stub-recv",
        )
        self._recv_thread.start()

    """ PUBLIC API """

    def getLots(self):
        '''Return list of {id, capacity, occupied, free}.'''
        return self._call("getLots")

    def getAvailability(self, lot_id: str) -> int:
        '''Return free space count for lot_id.'''
        return self._call("getAvailability", lot_id)

    def reserve(self, lot_id: str, plate: str) -> bool:
        '''Reserve a spot. Returns True. Raises RpcError on FULL/EXISTS.'''
        return self._call("reserve", lot_id, plate)

    def cancel(self, lot_id: str, plate: str) -> bool:
        '''Cancel a reservation. Returns True. Raises RpcError on NOT_FOUND.'''
        return self._call("cancel", lot_id, plate)

    """ PUB-SUB """

    def subscribe(self, lot_id: str) -> str:
        return self._call("subscribe", lot_id)

    def unsubscribe(self, sub_id: str) -> bool:
        return self._call("unsubscribe", sub_id)

    def close(self):
        self._sock.close()

    """ PRIVATE FUNCTIONS """

    def _recv_loop(self):
        while True:
            try:
                msg = self._recv()
            except (OSError, ConnectionError):
                self._reply_queue.put(None)   
                break

            if "event" in msg:
                cb = self.on_event
                if cb is not None:
                    try:
                        cb(msg["event"])
                    except Exception:
                        pass   
            else:
                self._reply_queue.put(msg)


    def _make_id(self):
        with self._id_lock:
            self._next_id += 1
            return self._next_id

    def _call(self, method, *args):
        rpc_id  = self._make_id()
        request = {"rpcId": rpc_id, "method": method, "args": list(args)}
        self._send(request)

        try:
            reply = self._reply_queue.get(timeout=self._timeout)
        except queue.Empty:
            raise RpcTimeoutError(
                f"No reply for '{method}' (rpcId={rpc_id}) "
                f"within {self._timeout}s"
            )

        if reply is None:
            raise ConnectionError("Server closed the connection")

        if reply.get("error"):
            raise RpcError(reply["error"])

        return reply["result"]

    def _send(self, obj):
        body   = json.dumps(obj).encode("utf-8")
        header = struct.pack("!I", len(body))
        self._sock.sendall(header + body)

    def _recv(self):
        header = self._recv_exact(4)
        length = struct.unpack("!I", header)[0]
        body   = self._recv_exact(length)
        return json.loads(body.decode("utf-8"))

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Server closed the connection unexpectedly")
            buf += chunk
        return buf
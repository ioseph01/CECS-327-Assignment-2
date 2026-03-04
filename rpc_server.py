import json
import struct
import logging

log = logging.getLogger(__name__)

# Receive rpc message from tcp connection
def recv_message(conn):
    header = _recv_exact(conn, 4)
    if header is None:
        raise ConnectionError("client disconnected")
    length = struct.unpack("!I", header)[0]
    body   = _recv_exact(conn, length)
    if body is None:
        raise ConnectionError("client disconnected mid-message")
    return body

# Send a rpc message over tcp
def send_message(conn, obj):
    body   = json.dumps(obj).encode("utf-8")
    header = struct.pack("!I", len(body))
    conn.sendall(header + body)

# Receive an n byte of data to read from socket.
def _recv_exact(conn, n):
    buffer = b""
    while len(buffer) < n:
        data_piece = conn.recv(n - len(buffer))
        if not data_piece:
            return None
        buffer += data_piece
    return buffer

RPC_METHODS = {}


# Server Skeleton handles client connection for RPC
def rpc_client(conn, addr, sem):
    from server import log_event   
    log_event("RPC_CONNECT", addr=str(addr))
    try:
        while True:
            # Request
            try:
                body = recv_message(conn)
            except ConnectionError:
                break
            try:
                req = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                send_message(conn, {"rpcId": None, "result": None,"error": "invalid JSON"})
                continue
            rpc_id = req.get("rpcId")
            method = req.get("method", "")
            args = req.get("args", [])
            log_event("RPC_CALL", rpcId=rpc_id, method=method, args=args)
            result = None
            error = None
            func = RPC_METHODS.get(method)
            if func is None:
                error = f"Unknown method '{method}'"
            else:
                try:
                    result = func(args, conn)
                except (ValueError, RuntimeError) as e:
                    error = str(e)
                except (IndexError, TypeError):
                    error = f"Wrong arguments for '{method}'"
            # Reply
            log_event("RPC_REPLY", rpcId=rpc_id, method=method, result=result, error=error)
            send_message(conn, {"rpcId": rpc_id, "result": result, "error": error})
    except OSError:
        pass
    finally:
        conn.close()
        sem.release()
        log_event("RPC_DISCONNECT", addr=str(addr))
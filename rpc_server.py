import json
import struct
import logging

log = logging.getLogger(__name__)


def recv_message(conn):
    header = _recv_exact(conn, 4)
    if header is None:
        raise ConnectionError("client disconnected")
    length = struct.unpack("!I", header)[0]
    body   = _recv_exact(conn, length)
    if body is None:
        raise ConnectionError("client disconnected mid-message")
    return body


def send_message(conn, obj):
    body   = json.dumps(obj).encode("utf-8")
    header = struct.pack("!I", len(body))
    conn.sendall(header + body)


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf



RPC_METHODS = {}


""" SKELETON SERVER """
def handle_rpc_client(conn, addr, sem):
    ''' RPC skeleton loop ''' 
    from server import log_event   
    log_event("RPC_CONNECT", addr=str(addr))
    try:
        while True:
            # Receive 
            try:
                body = recv_message(conn)
            except ConnectionError:
                break

            try:
                req = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                send_message(conn, {"rpcId": None, "result": None,
                                    "error": "invalid JSON"})
                continue

            rpc_id = req.get("rpcId")
            method = req.get("method", "")
            args   = req.get("args", [])

            log_event("RPC_CALL", rpcId=rpc_id, method=method, args=args)

            # Dispatch
            result = None
            error  = None
            fn     = RPC_METHODS.get(method)

            if fn is None:
                error = f"unknown method '{method}'"
            else:
                try:
                    result = fn(args, conn)
                except (ValueError, RuntimeError) as e:
                    error = str(e)
                except (IndexError, TypeError):
                    error = f"wrong arguments for '{method}'"

            # Reply
            log_event("RPC_REPLY", rpcId=rpc_id, method=method,
                      result=result, error=error)
            send_message(conn, {"rpcId": rpc_id, "result": result,
                                "error": error})

    except OSError:
        pass
    finally:
        conn.close()
        sem.release()
        log_event("RPC_DISCONNECT", addr=str(addr))
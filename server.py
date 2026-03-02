import socket
import threading
import json
import struct
import logging
import uuid
import datetime
import time
import queue as queue_module
import os


""" LOGGING """
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def log_event(event, **kwargs):
    entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "event": event}
    entry.update(kwargs)
    log.info(json.dumps(entry))


""" CONFIGURATION """

def load_config(path="config.json"):
    script_dir  = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, path)
    with open(config_path) as f:
        return json.load(f)

CONFIG         = load_config()
TEXT_PORT      = CONFIG["ports"]["text"]
RPC_PORT       = CONFIG["ports"]["rpc"]
SENSOR_PORT    = CONFIG["ports"]["sensor"]
SERVER_HOST    = CONFIG["server_host"]
MAX_CLIENTS    = CONFIG["threading"]["max_clients"]
BACKLOG        = CONFIG["threading"]["backlog"]
SENSOR_WORKERS = CONFIG["threading"]["sensor_workers"]
TTL_SECONDS    = CONFIG["reservations"]["ttl_seconds"]
EXPIRY_INTERVAL= CONFIG["reservations"]["expiry_interval"]
SUB_QUEUE_SIZE = CONFIG["pubsub"]["subscriber_queue_size"]
SENSOR_Q_MAX   = CONFIG["sensor_queue"]["max_size"]


""" SHARED STATE """
state_lock = threading.Lock()

lots = {}
for _lot in CONFIG["lots"]:
    lots[_lot["id"]] = {
        "capacity":     _lot["capacity"],
        "occupied":     0,
        "reservations": {},   # plate -> expiry timestamp
    }

def free_spaces(lot):
    return lot["capacity"] - lot["occupied"] - len(lot["reservations"])


""" RESERVATIONS """
def expiry_worker():
    log_event("EXPIRY_WORKER_START", interval=EXPIRY_INTERVAL, ttl=TTL_SECONDS)
    while True:
        time.sleep(EXPIRY_INTERVAL)
        now        = time.time()
        to_publish = []
        with state_lock:
            for lot_id, lot in lots.items():
                expired = [p for p, exp in lot["reservations"].items() if exp <= now]
                for plate in expired:
                    del lot["reservations"][plate]
                    log_event("RESERVE_EXPIRED", lotId=lot_id, plate=plate,
                              free=free_spaces(lot))
                if expired:
                    to_publish.append((lot_id, free_spaces(lot)))
        for lot_id, free in to_publish:
            publish(lot_id, free)


""" PUB-SUB """
sub_lock    = threading.Lock()
subscribers = {}   # { lot_id: { sub_id: Queue } }


def publish(lot_id, free):
    ts  = datetime.datetime.now(datetime.timezone.utc).isoformat()
    msg = f"EVENT {lot_id} {free} {ts}"
    with sub_lock:
        for sub_id, q in subscribers.get(lot_id, {}).items():
            try:
                q.put_nowait(msg)
            except queue_module.Full:
                try:
                    q.get_nowait()        # drop oldest
                    q.put_nowait(msg)     # add newest
                    log_event("PUBSUB_DROP_OLDEST", subId=sub_id, lotId=lot_id)
                except queue_module.Empty:
                    pass


def _get_lots():
    with state_lock:
        return [{"id": lot_id, "capacity": lot["capacity"],
                 "occupied": lot["occupied"], "free": free_spaces(lot)}
                for lot_id, lot in lots.items()]


def _get_availability(lot_id):
    with state_lock:
        if lot_id not in lots:
            raise ValueError(f"unknown lot '{lot_id}'")
        return free_spaces(lots[lot_id])


def _reserve(lot_id, plate):
    with state_lock:
        if lot_id not in lots:
            raise ValueError(f"unknown lot '{lot_id}'")
        lot = lots[lot_id]
        if plate in lot["reservations"]:
            raise RuntimeError("EXISTS")
        if free_spaces(lot) <= 0:
            raise RuntimeError("FULL")
        lot["reservations"][plate] = time.time() + TTL_SECONDS
        free = free_spaces(lot)
        log_event("RESERVE", lotId=lot_id, plate=plate, free=free,
                  expires_in=TTL_SECONDS)
    publish(lot_id, free)
    return True


def _cancel(lot_id, plate):
    with state_lock:
        if lot_id not in lots:
            raise ValueError(f"unknown lot '{lot_id}'")
        lot = lots[lot_id]
        if plate not in lot["reservations"]:
            raise RuntimeError("NOT_FOUND")
        del lot["reservations"][plate]
        free = free_spaces(lot)
        log_event("CANCEL", lotId=lot_id, plate=plate, free=free)
    publish(lot_id, free)
    return True


def _sensor_update(lot_id, delta):
    with state_lock:
        if lot_id not in lots:
            log_event("SENSOR_UNKNOWN_LOT", lotId=lot_id, delta=delta)
            return "ERROR unknown lot"
        lot     = lots[lot_id]
        max_occ = lot["capacity"] - len(lot["reservations"])
        if delta < 0 and lot["occupied"] <= 0:
            log_event("SENSOR_REJECTED", lotId=lot_id, delta=delta,
                      reason="occupied already 0")
            return "ERROR lot already empty"
        if delta > 0 and lot["occupied"] >= max_occ:
            log_event("SENSOR_REJECTED", lotId=lot_id, delta=delta,
                      reason="lot already full")
            return "ERROR lot already full"
        old_occ = lot["occupied"]
        lot["occupied"] = max(0, min(max_occ, old_occ + delta))
        free = free_spaces(lot)
        log_event("SENSOR_UPDATE", lotId=lot_id, delta=delta,
                  occupied_before=old_occ, occupied_after=lot["occupied"],
                  free=free)
    publish(lot_id, free)
    return "OK"


def _subscribe(lot_id, conn):
    if lot_id not in lots:
        raise ValueError(f"unknown lot '{lot_id}'")
    sub_id = uuid.uuid4().hex[:8]
    q      = queue_module.Queue(maxsize=SUB_QUEUE_SIZE)
    with sub_lock:
        subscribers.setdefault(lot_id, {})[sub_id] = q
    threading.Thread(
        target=_notifier_thread, args=(conn, sub_id, q),
        daemon=True, name=f"notifier-{sub_id}",
    ).start()
    log_event("SUBSCRIBE", subId=sub_id, lotId=lot_id)
    return sub_id


def _unsubscribe(sub_id):
    with sub_lock:
        for lot_id, lot_subs in subscribers.items():
            if sub_id in lot_subs:
                q = lot_subs.pop(sub_id)
                try:
                    q.put_nowait(None)
                except queue_module.Full:
                    q.get_nowait()
                    q.put_nowait(None)
                log_event("UNSUBSCRIBE", subId=sub_id, lotId=lot_id)
                return True
    return False


def _notifier_thread(conn, sub_id, q):
    """Dedicated thread per subscriber — drains its queue and sends events."""
    from rpc_server import send_message
    log_event("NOTIFIER_START", subId=sub_id)
    while True:
        event = q.get(block=True)
        if event is None:
            break
        try:
            send_message(conn, {"event": event})
        except OSError:
            _unsubscribe(sub_id)
            break
    log_event("NOTIFIER_STOP", subId=sub_id)


def text_dispatch(line):
    parts = line.strip().split()
    if not parts:
        return None
    cmd = parts[0].upper()
    if cmd == "PING":
        return "PONG"
    elif cmd == "LOTS":
        return json.dumps(_get_lots())
    elif cmd == "AVAIL":
        if len(parts) < 2:
            return "ERROR usage: AVAIL <lotId>"
        try:
            return str(_get_availability(parts[1]))
        except ValueError as e:
            return f"ERROR {e}"
    elif cmd == "RESERVE":
        if len(parts) < 3:
            return "ERROR usage: RESERVE <lotId> <plate>"
        try:
            _reserve(parts[1], parts[2])
            return "OK"
        except (ValueError, RuntimeError) as e:
            return str(e)
    elif cmd == "CANCEL":
        if len(parts) < 3:
            return "ERROR usage: CANCEL <lotId> <plate>"
        try:
            _cancel(parts[1], parts[2])
            return "OK"
        except (ValueError, RuntimeError) as e:
            return str(e)
    else:
        return f"ERROR unknown command '{cmd}'"


def handle_text_client(conn, addr, sem):
    log_event("TEXT_CONNECT", addr=str(addr))
    try:
        for raw_line in conn.makefile("rb"):
            resp = text_dispatch(raw_line.decode("utf-8", errors="replace"))
            if resp is not None:
                conn.sendall((resp + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        conn.close()
        sem.release()
        log_event("TEXT_DISCONNECT", addr=str(addr))


""" SENSOR """
update_queue = queue_module.Queue(maxsize=SENSOR_Q_MAX)


def sensor_worker(worker_id):
    log_event("SENSOR_WORKER_START", workerId=worker_id)
    while True:
        lot_id, delta = update_queue.get(block=True)
        _sensor_update(lot_id, delta)
        update_queue.task_done()


def handle_sensor_client(conn, addr, sem):
    log_event("SENSOR_CONNECT", addr=str(addr))
    try:
        for raw_line in conn.makefile("rb"):
            line  = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3 or parts[0].upper() != "UPDATE":
                conn.sendall(b"ERROR usage: UPDATE <lotId> <delta>\n")
                continue
            try:
                delta = int(parts[2])
            except ValueError:
                conn.sendall(b"ERROR delta must be integer\n")
                continue
            try:
                update_queue.put_nowait((parts[1], delta))
                conn.sendall(b"OK\n")
            except queue_module.Full:
                conn.sendall(b"ERROR server queue full, retry later\n")
                log_event("SENSOR_QUEUE_FULL", lotId=parts[1], delta=delta)
    except OSError:
        pass
    finally:
        conn.close()
        sem.release()
        log_event("SENSOR_DISCONNECT", addr=str(addr))


""" COMMUNICATIONS """
def run_tcp_server(host, port, handler, label):
    sem  = threading.Semaphore(MAX_CLIENTS)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(BACKLOG)
    log_event("SERVER_START", label=label, port=port,
              max_clients=MAX_CLIENTS, backlog=BACKLOG)
    while True:
        conn, addr = sock.accept()
        if not sem.acquire(blocking=False):
            conn.sendall(b"ERROR server full\n")
            conn.close()
            log_event("CONNECTION_REJECTED", label=label, addr=str(addr),
                      reason="server full")
            continue
        threading.Thread(
            target=handler, args=(conn, addr, sem),
            daemon=True, name=f"{label}-{addr[1]}",
        ).start()


def main():
    from rpc_server import RPC_METHODS, handle_rpc_client
    RPC_METHODS["getLots"]         = lambda args, conn: _get_lots()
    RPC_METHODS["getAvailability"] = lambda args, conn: _get_availability(args[0])
    RPC_METHODS["reserve"]         = lambda args, conn: _reserve(args[0], args[1])
    RPC_METHODS["cancel"]          = lambda args, conn: _cancel(args[0], args[1])
    RPC_METHODS["subscribe"]       = lambda args, conn: _subscribe(args[0], conn)
    RPC_METHODS["unsubscribe"]     = lambda args, conn: _unsubscribe(args[0])

    log_event("STARTUP", config=CONFIG)

    threading.Thread(target=expiry_worker, daemon=True, name="expiry-worker").start()

    for i in range(SENSOR_WORKERS):
        threading.Thread(target=sensor_worker, args=(i,),
                         daemon=True, name=f"sensor-worker-{i}").start()

    threading.Thread(
        target=run_tcp_server,
        args=(SERVER_HOST, SENSOR_PORT, handle_sensor_client, "SENSOR"),
        daemon=True, name="sensor-server",
    ).start()

    threading.Thread(
        target=run_tcp_server,
        args=(SERVER_HOST, TEXT_PORT, handle_text_client, "TEXT"),
        daemon=True, name="text-server",
    ).start()

    try:
        run_tcp_server(SERVER_HOST, RPC_PORT, handle_rpc_client, "RPC")
    except KeyboardInterrupt:
        log_event("SHUTDOWN")


if __name__ == "__main__":
    main()
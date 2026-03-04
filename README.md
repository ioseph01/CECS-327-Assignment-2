# CECS-327-Assignment-2: Campus Smart Parking Finder 

## Setup:
No dependencies except Python and built-in libraries are used so there is no need to create a virtual environment and activate it.

## To Run:

In one terminal, launch the server with `python3 server.py`.

In a second terminal, launch the sensor simulation with `python3 sensor.py`.

In one or more terminals, launch clients with `python3 client.py`.

## Then type commands like:
- `PING`
- `LOTS`
- `RESERVE <lot> ABC123`
- `AVAIL <lot>`
- `CANCEL <lot> ABC123`
- `SUB <lot>`
- `UNSUB <lot>`
- `HELP`
## RPC path
client.py -> client_stub.py -> TCP -> rpc_skeleton.py -> server.py -> rpc_skeleton.py -> client_stub.py -> client.py

## Note about endianess: 
JSON is used so not too much worry about endianess. The concern becomes data managing, message formatting, and error handling. In that case, we use a struct and big endian bytes denoted by "!I". 

## Timeout Policy
For clients, the server sets a 60-second idle timeout. If a connection is established but nothing is sent, the client is quietly dropped and its thread is freed.

## Publish/Subscribe System
The approach we took for our design was a mix of both TCP connections for events and dedicated notifier threads for subscriptions. Subscribed clients are dedicated a thread and queue for non-blocking while the separate TCP connection is for distinct connections between RPC requests and event reception.

## Configuration
Important file settings such as the number of worker threads, ports for sockets, or the size of queues are all defined in a configs.json. This file is loaded into each of the python files and read for any configuration values.

## Back-Pressure Policy
The current policy for handling slow subscribers and back-pressure is discarding the oldest message in a subscriber's update queue to make room for the newest. This action is logged appropriately unless the client's TCP errors in which case, the client is unsubscribed. The reason for dropping the oldest is because clients that are subscribed should only care about the present state of the lot so the most recent updates from the sensor are more valuable. Older updates on the other hand are already missed and do not provide any valuable information about the current lot state. 


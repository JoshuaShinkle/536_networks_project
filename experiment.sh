#!/bin/bash

./exec.sh h1 python server.py 10.0.0.1 10001
./exec.sh h2 python server.py 10.0.0.2 10001
./exec.sh h3 python server.py 10.0.0.3 10001
./exec.sh h4 python server.py 10.0.0.4 10001

./exec.sh h1 python client.py 10.0.0.2 10001 10
./exec.sh h2 python client.py 10.0.0.3 10001 10
./exec.sh h3 python client.py 10.0.0.4 10001 10 
./exec.sh h4 python client.py 10.0.0.1 10001 10 

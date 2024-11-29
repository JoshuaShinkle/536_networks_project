cd /mn_scripts
h1 python3 -u /mn_scripts/server.py 10.0.0.1 10001 &
# h2 python -u server.py 10.0.0.2 10001 &
# h3 python -u server.py 10.0.0.3 10001 &
# h4 python -u server.py 10.0.0.4 10001 &
# h1 python -u client.py 10.0.0.2 10001 10 & 
h2 python3 -u /mn_scripts/client.py 10.0.0.1 10001 10 &
# h3 python -u client.py 10.0.0.4 10001 10 &
# h3 python -u client.py 10.0.0.1 10001 10 &





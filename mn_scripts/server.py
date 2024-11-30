import threading
import socket
import argparse
import time

def main():
    parser = argparse.ArgumentParser(description='Run experiment server')
    parser.add_argument('ip', help='IP address to open server on')
    parser.add_argument('port', type=int, help='Port number')

    args = parser.parse_args()
    
    # Create a TCP socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((args.ip, args.port))
    server.listen(5)

    while True:
            
        # Accept client connections
        client_socket, client_address = server.accept()
        print("Accepted connection from " + str(client_address))

        # Handle the connection in a new thread
        client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address, args.ip))
        client_thread.start()


def handle_client(client_socket, client_address, server_ip):
    bytes_received = 0 
    start_time = time.time()

    try:
        # Receive data from the client
        while True:
            data = client_socket.recv(1024)

            if not data:
                # If no data is received, the client has closed the connection
                break
            
            bytes_received += 1024
            # print("Received data: " + data.decode('utf-8'))
    
    except Exception as e:
        print("Error handling client: " + str(e))

    finally:
        end_time = time.time()
        client_ip = client_address[0]
        client_port = client_address[1]

        filename = f"stats_serverip={server_ip}_clientip={client_ip}_clientport={client_port}"
        with open(filename, "w") as f:
            f.write(str(start_time) + ",")
            f.write(str(end_time) + ",")
            f.write(str(server_ip) + ",")
            f.write(str(client_ip) + ",")
            f.write(str(client_port) + ",")
            f.write(str(bytes_received) + "\n")

        # Close the connection
        client_socket.close()

if __name__ == '__main__':
    main()

import threading
import socket
import argparse

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
        client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address,))
        client_thread.start()


def handle_client(client_socket, address):
    bytes = 0 

    try:
        # Receive data from the client
        while True:
            data = client_socket.recv(1024)

            if not data:
                # If no data is received, the client has closed the connection
                break
            
            bytes += 1024
            # print("Received data: " + data.decode('utf-8'))
    
    except Exception as e:
        print("Error handling client: " + str(e))
                                                                                                            
    finally:
        filename = f"/mn_scripts/stats_{address[0]}_{address[1]}"
        with open(filename, "w") as f:
            f.write(str(bytes) + "\n")

        print(f"Received {bytes} bytes from host {address[0]} on port {address[1]}") 
        # Close the connection
        client_socket.close()

if __name__ == '__main__':
    main()

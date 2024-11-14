import socket
import time
import argparse
import multiprocessing

def create_connection(host, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        print("Connection succeeded")

        start_time = time.time()
        while time.time() - start_time < 5:
            sock.sendall("Random message".encode('utf-8'))

        return sock

    except Exception as e:
        print("Connection failed: " + str(e))
        return None

    finally:
        sock.close()
        print("Closed socket")

def main():
    parser = argparse.ArgumentParser(description='Run experiment client')
    parser.add_argument('ip', help='IP address to connect to')
    parser.add_argument('port', type=int, help='Port number')
    parser.add_argument('num_flows', type=int, help='Number of TCP connections to create')
    
    args = parser.parse_args()

    processes = []

    # Create specified number of connections
    for i in range(args.num_flows):

        # Create a process for each flow to send packets
        process = multiprocessing.Process(target=create_connection, args=(args.ip, args.port))
        processes.append(process)
        process.start()

    for p in processes:
        p.join()


if __name__ == '__main__':
    main()

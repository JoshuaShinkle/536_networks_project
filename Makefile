help: 
	@echo "Example usage ...\n"
	@echo "- Start Evironment (Ryu controller + mininet): make environment\n"

environment:
	docker compose up --build -d

mininet_renet:
	docker exec -it mininet bash -c "python3 setup_mininet_experiement.py"

ryu_simple:
	docker exec -it ryu_controller bash -c "ryu-manager ryu.app.simple_switch"

ryu_renet:
	docker exec -it ryu_controller bash -c "ryu-manager --observe-links renet.py"

restart:
	docker restart mininet

clean:
	# Stop and remove all running containers
	docker-compose down --volumes --remove-orphans
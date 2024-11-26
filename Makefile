help: 
	@echo "Example usage ...\n"
	@echo "- Start Evironment (Ryu controller + mininet): make environment\n"

environment:
	docker compose up --build -d

mininet_bash:
	docker exec -it mininet bash

ryu_bash:
	docker exec -it ryu_controller bash

clean:
	# Stop and remove all running containers
	docker-compose down --volumes --remove-orphans
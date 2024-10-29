SCRIPTS = $(CURDIR)/scripts

export name ?=

MAKEFLAGS += --no-print-directory

.PHONY: mininet controller cli netcfg host-h1 host-h2 tests

# Custom topology variables
TOPO_FILE = paper_topology.py
TOPO_CLASS = mytopo

help: 
	@echo "Example usage ...\n"
	@echo "- Start Mininet: make mininet\n"
	@echo "- Install Mininet Prereqs/Dependencies: make mininet-prereqs\n"
	@echo "- Start Controller: make controller\n"
	@echo "- Controller CLI: make cli (password is rocks)\n"
	@echo "- Connect Controller to Mininet: make netcfg\n"
	@echo "- Compile Server/Client Binaries: make client-server\n"
	@echo "- Run Tests: make tests\n"
	@echo "- Access Host: make host name=h1\n"
	@echo "- Clean All: make clean\n"
	@echo "- Start Custom Mininet Topology: make mininet TOPO_FILE=<path_to_file> TOPO_CLASS=<topo_class_name>\n"

mininet:
	$(SCRIPTS)/mn-stratum --custom $(TOPO_FILE) --topo $(TOPO_CLASS)
	make clean


controller:
	ONOS_APPS=gui,proxyarp,drivers.bmv2,lldpprovider,hostprovider,fwd \
	$(SCRIPTS)/onos

cli:
	$(SCRIPTS)/onos-cli

netcfg:
	$(SCRIPTS)/onos-netcfg cfg/netcfg.json

# Usage: make host name=h1
host:
	$(SCRIPTS)/utils/mn-stratum/exec $(name)

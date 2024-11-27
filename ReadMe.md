# Project Title

Description

## Table of Contents

## Installation

1. Clone the Repo

2. Ensure docker is installed

## Starting the containers

From local computer or EC2:

Also run this if you modify the Dockerfile

`$ docker compose build`

Then run the containers:

`$ docker compose up`

This starts the mininet and ryu_controller containers. The folder `./mn_scripts` will be automatically mounted to the `/mn_scripts` directory in the mininet container, and same with `./ryu_app` to `/ryu_app` in the ryu_controller container. So you can edit files locally and they'll show up in the container.

To access the containers (run bash inside the container):

`$ docker exec -it mininet bash`

or

`$ docker exec -it ryu_controller bash`

`exec` means ececute command, `-it` means interactive terminal, followed by the container name, followed by `bash`, the command to execute. If you only need to do a single command without interactivity, you can change the command.

E.g. just `ryu-manager renet.py` with no interactivity:

`$ docker exec ryu_controller ryu-manager /ryu_app/renet.py`

## Running controller code

You can either interactively enter the docker container and run commands as described above, or run a single command in the docker container with `docker exec`.

For ryu, it is `ryu-manager <controller_code.py>`

So either:
```
user@local_computer:~$ docker exec -it ryu_controller bash
root@ryu_container# ryu-manager /ryu_app/renet.py
```

or just `docker exec ryu_controller ryu-manager /ryu_app/renet.py`

## Running mininet

For mininet it is ran with python, so do `python3 /mn_scripts/setup_mininet_experiment.py` from within the mininet container.

For now, we have the containers running on the host network, so the IP for the ryu_controller is 127.0.0.1 which you will have to specify in the python code when connecting the controller.

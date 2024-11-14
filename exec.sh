#!/bin/bash

MN_STRATUM_DOCKER_NAME=${MN_STRATUM_DOCKER_NAME:-mn-stratum}
HOST_NAME=$1
CMD=$2

docker exec -d $MN_STRATUM_DOCKER_NAME \
	  /bin/bash -c \
	    "mkdir -p /run/netns; \
	      touch /run/netns/$HOST_NAME >/dev/null 2>&1; \
	        PID=\$(ps -ef | awk '\$12 ~ /mininet:$HOST_NAME/ {print \$2}'); \
		  mount -o bind /proc/\$PID/ns/net /run/netns/$HOST_NAME; \
		    ip netns exec $HOST_NAME bash -c \"$2\""


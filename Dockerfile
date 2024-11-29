# Use a stable Python image as the base
FROM python:3.9-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    net-tools \
    iputils-ping \
    && apt-get clean

# Install Ryu from the source
RUN git clone https://github.com/faucetsdn/ryu.git /opt/ryu \
    && pip install -e /opt/ryu

RUN pip install networkx

# Set the working directory
WORKDIR /ryu_app

# Expose ports
EXPOSE 6633
EXPOSE 8080

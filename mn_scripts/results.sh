#!/bin/bash

output_file="aggregated_stats.csv"

# Write the CSV header
echo "start_time,end_time,server_ip,client_ip,client_port,bytes_received" > "$output_file"

# Iterate through files starting with "stats"
for file in stats*; do
	if [[ -f "$file" ]]; then
		cat "$file" >> "$output_file"
	fi
done

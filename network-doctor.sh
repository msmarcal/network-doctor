#!/bin/bash

# Network Connectivity Report Generator for Juju Magpie Status
# Analyzes juju status JSON output to identify network communication issues

set -euo pipefail

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed. Please install jq first." >&2
    exit 1
fi

# Read from stdin or file
if [[ $# -eq 0 ]]; then
    # Read from stdin
    JSON_DATA=$(cat)
else
    # Read from file
    INPUT_FILE="$1"
    if [[ ! -f "$INPUT_FILE" ]]; then
        echo "Error: Input file '$INPUT_FILE' not found." >&2
        echo "Usage: $0 [juju-status.json] or cat juju-status.json | $0" >&2
        exit 1
    fi
    JSON_DATA=$(cat "$INPUT_FILE")
fi

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "=========================================="
echo "    JUJU MAGPIE NETWORK REPORT"
echo "=========================================="
echo ""

# Extract basic information
model_name=$(echo "$JSON_DATA" | jq -r '.model.name')
total_machines=$(echo "$JSON_DATA" | jq '.machines | length')
total_apps=$(echo "$JSON_DATA" | jq '.applications | length')

echo "Model: $model_name"
echo "Total Machines: $total_machines"
echo "Total Magpie Applications: $total_apps"
echo ""

# Get machine information
echo "MACHINE INVENTORY:"
echo "=================="
echo "$JSON_DATA" | jq -r '.machines | to_entries[] | 
    "\(.key): \(.value.hostname) (\(.value["display-name"])) - \(.value["dns-name"]) - Zone: \(.value.hardware | split(" ") | map(select(startswith("availability-zone="))) | .[0] | split("=")[1])"' | 
    while read -r line; do
        echo "  $line"
    done
echo ""

# Analyze network spaces and their status
echo "NETWORK SPACE ANALYSIS:"
echo "======================"

# Get all magpie applications and their status
echo "$JSON_DATA" | jq -r '.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    "\(.key):\(.value["application-status"].current):\(.value["application-status"].message)"' | 
    while IFS=: read -r app_name status message; do
        space_name=$(echo "$app_name" | sed 's/magpie-//')
        
        echo -n "  $space_name: "
        if [[ "$status" == "active" ]]; then
            echo -e "${GREEN}✓ HEALTHY${NC}"
        elif [[ "$status" == "blocked" ]]; then
            echo -e "${RED}✗ ISSUES DETECTED${NC}"
        else
            echo -e "${YELLOW}⚠ $status${NC}"
        fi
        
        if [[ "$status" == "blocked" ]]; then
            echo "    Issue: $message"
        fi
        echo ""
    done

echo ""
echo "DETAILED UNIT ANALYSIS:"
echo "======================"

# Analyze each magpie application's units
echo "$JSON_DATA" | jq -r '.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    .key as $app | .value.units | to_entries[] | 
    "\($app)|\(.key)|\(.value.machine)|\(.value["workload-status"].current)|\(.value["workload-status"].message)"' | 
    while IFS='|' read -r app_name unit_name machine_id status message; do
        space_name=$(echo "$app_name" | sed 's/magpie-//')
        
        if [[ "$status" != "active" ]]; then
            echo -e "${RED}PROBLEM DETECTED:${NC}"
            echo "  Network Space: $space_name"
            echo "  Unit: $unit_name (Machine $machine_id)"
            echo "  Status: $status"
            echo "  Details: $message"
            echo ""
        fi
    done

echo ""
echo "CONNECTIVITY MATRIX:"
echo "==================="

# Create a connectivity matrix showing which machines can't reach others
echo "Analyzing ICMP connectivity failures..."
echo ""

# Get machine hostnames for reference
declare -A machine_names
while IFS='|' read -r machine_id hostname; do
    machine_names[$machine_id]=$hostname
done < <(echo "$JSON_DATA" | jq -r '.machines | to_entries[] | "\(.key)|\(.value.hostname)"')

# Track failed connections per machine
declare -A connectivity_issues

echo "$JSON_DATA" | jq -r '.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    .key as $app | .value.units | to_entries[] | 
    select(.value["workload-status"].current == "blocked") |
    "\($app)|\(.value.machine)|\(.value["workload-status"].message)"' | 
    while IFS='|' read -r app_name source_machine message; do
        space_name=$(echo "$app_name" | sed 's/magpie-//')
        source_hostname=${machine_names[$source_machine]}
        
        # Extract failed machine IDs from ICMP failure messages
        if [[ "$message" =~ icmp\ failed:\ ([0-9,\ ]+): ]]; then
            failed_machines=$(echo "${BASH_REMATCH[1]}" | tr ';' '\n' | grep -o '[0-9]\+' | sort -u)
            
            echo -e "${RED}Machine $source_machine ($source_hostname) in $space_name:${NC}"
            for failed_machine in $failed_machines; do
                failed_hostname=${machine_names[$failed_machine]}
                echo "  ↳ Cannot reach Machine $failed_machine ($failed_hostname)"
            done
            echo ""
        fi
        
        # Check for DNS issues
        if [[ "$message" =~ rev\ dns\ failed:\ \[([^\]]+)\] ]]; then
            failed_dns_machines=$(echo "${BASH_REMATCH[1]}" | tr "'" " " | tr "," "\n" | grep -o '[0-9]\+')
            echo -e "${YELLOW}DNS Resolution Issues from Machine $source_machine ($source_hostname) in $space_name:${NC}"
            for dns_machine in $failed_dns_machines; do
                dns_hostname=${machine_names[$dns_machine]}
                echo "  ↳ Cannot resolve Machine $dns_machine ($dns_hostname)"
            done
            echo ""
        fi
    done

echo ""
echo "MACHINE-FOCUSED SUMMARY:"
echo "======================="

# Generate machine-focused summary using jq grouping
echo "$JSON_DATA" | jq -r '
# Group blocked units by machine
[.applications | to_entries[] | select(.key | startswith("magpie-")) | 
 .key as $app | .value.units | to_entries[] | 
 select(.value["workload-status"].current == "blocked") |
 {
   app: $app,
   machine: .value.machine,
   space: ($app | sub("magpie-"; "")),
   message: .value["workload-status"].message,
   hostname: ""
 }] | 
group_by(.machine) | 
sort_by(.[0].machine | tonumber) |
.[] | 
{
  machine: .[0].machine,
  spaces: [.[].space] | unique,
  space_count: ([.[].space] | unique | length),
  dns_issues: ([.[].message | select(contains("rev dns failed"))] | length > 0)
} |
"\(.machine)|\(.space_count)|\(.spaces | join(","))|\(.dns_issues)"
' | while IFS='|' read -r machine_id space_count spaces dns_issues; do
    machine_hostname=${machine_names[$machine_id]}
    
    echo ""
    if [[ $space_count -ge 4 ]]; then
        echo -e "${RED}Machine $machine_id ($machine_hostname) - CRITICAL:${NC}"
        echo "├── Cannot reach other machines on:"
        echo "$spaces" | tr ',' '\n' | while read -r space; do
            # Get MTU info for this space  
            if [[ "$space" =~ ^(ceph-access-space|ceph-replica-space|provider-space|public-space)$ ]]; then
                mtu_info=" (MTU 9000)"
            else
                mtu_info=" (MTU 1500)"
            fi
            echo "│   ├── $space$mtu_info"
        done
        
        if [[ "$dns_issues" == "true" ]]; then
            echo "└── DNS resolution failing for multiple machines"
        fi
    else
        echo -e "${YELLOW}Machine $machine_id ($machine_hostname) - ISSUES:${NC}"
        echo "└── Problems on: $(echo "$spaces" | tr ',' ' ')"
    fi
done

echo ""
echo "SUMMARY & RECOMMENDATIONS:"
echo "=========================="

# Count issues
blocked_units=$(echo "$JSON_DATA" | jq '[.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    .value.units | to_entries[] | select(.value["workload-status"].current == "blocked")] | length')

active_spaces=$(echo "$JSON_DATA" | jq '[.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    select(.value["application-status"].current == "active")] | length')

blocked_spaces=$(echo "$JSON_DATA" | jq '[.applications | to_entries[] | select(.key | startswith("magpie-")) | 
    select(.value["application-status"].current == "blocked")] | length')

echo "  • Healthy network spaces: $active_spaces"
echo "  • Network spaces with issues: $blocked_spaces" 
echo "  • Units with connectivity problems: $blocked_units"
echo ""

if [[ $blocked_units -gt 0 ]]; then
    echo -e "${RED}CRITICAL ISSUES FOUND:${NC}"
    echo "  1. Check physical network connectivity between machines"
    echo "  2. Verify VLAN configuration and network space bindings"
    echo "  3. Inspect firewall rules and routing tables"
    echo "  4. Validate MTU settings across network interfaces"
    echo "  5. Check DNS configuration for reverse lookups"
else
    echo -e "${GREEN}✓ All network spaces are healthy!${NC}"
fi

echo ""
echo "Report generated: $(date)"
echo "=========================================="
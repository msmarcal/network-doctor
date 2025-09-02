# Network Doctor

A bash script that analyzes Juju Magpie network connectivity status and generates human-readable reports to identify network communication issues between machines.

## Overview

This tool processes JSON output from `juju status --format json` for deployments using the Magpie charm, which tests network connectivity between Juju machines across different network spaces. It identifies which machines cannot communicate with others and provides actionable insights for network troubleshooting.

## Features

- **Machine Inventory**: Lists all machines with hostnames, IP addresses, and availability zones
- **Network Space Analysis**: Shows health status of each network space (oam, internal, ceph-access, etc.)
- **Machine-Focused Summary**: Identifies critical machines with widespread connectivity issues
- **Connectivity Matrix**: Detailed ICMP and DNS failure analysis between machines
- **MTU Information**: Shows required MTU settings for each network space
- **Color-coded Output**: Uses colors to highlight critical issues, warnings, and healthy status

## Requirements

- `jq` - JSON processor for parsing Juju status output
- `bash` 4.0+ - For associative arrays and modern bash features

## Installation

1. Clone this repository or download the script:

   ```bash
   chmod +x network-doctor.sh
   ```

2. Install `jq` if not already available:

   ```bash
   # Ubuntu/Debian
   sudo apt install jq
   ```

## Usage

The script can read Juju status data from stdin or from a file:

### From stdin (recommended)

```bash
juju status --format json | ./network-doctor.sh
```

### From file

```bash
juju status --format json > juju-status.json
./network-doctor.sh juju-status.json
```

## Example Output

```
==========================================
    JUJU MAGPIE NETWORK REPORT
==========================================

Model: magpie
Total Machines: 5
Total Magpie Applications: 6

MACHINE INVENTORY:
==================
  0: node-01 (node-01) - 10.0.1.10 - Zone: zone3
  1: node-02 (node-02) - 10.0.1.11 - Zone: zone2
  2: node-03 (node-03) - 10.0.1.12 - Zone: zone1
  3: node-04 (node-04) - 10.0.1.13 - Zone: zone1
  4: node-05 (node-05) - 10.0.1.14 - Zone: zone3

NETWORK SPACE ANALYSIS:
======================
  oam-space: ✓ HEALTHY
  ceph-access-space: ✗ ISSUES DETECTED
  internal-space: ✗ ISSUES DETECTED
  ...

MACHINE-FOCUSED SUMMARY:
=======================

Machine 2 (node-03) - CRITICAL:
├── Cannot reach other machines on:
│   ├── ceph-access-space (MTU 9000)
│   ├── ceph-replica-space (MTU 9000)
│   ├── internal-space (MTU 1500)
│   ├── provider-space (MTU 9000)
│   └── public-space (MTU 9000)
└── DNS resolution failing for multiple machines
```

## Understanding the Output

### Status Indicators

- **✓ HEALTHY**: Network space has no connectivity issues
- **✗ ISSUES DETECTED**: Network space has blocking connectivity problems
- **⚠ WARNING**: Network space has non-blocking issues

### Machine Classifications

- **CRITICAL**: Machine has connectivity issues on 4+ network spaces
- **ISSUES**: Machine has problems on fewer network spaces

### Common Issues Identified

- **ICMP failures**: `0/20 packets received` indicates packet loss between machines
- **DNS resolution failures**: `rev dns failed` shows reverse DNS lookup problems
- **MTU mismatches**: Required vs actual MTU settings

## Network Spaces

Common Juju network spaces tested by Magpie:

- **oam-space**: Operations, Administration, and Maintenance (MTU 1500)
- **internal-space**: Internal service communication (MTU 1500)
- **ceph-access-space**: Ceph client access network (MTU 9000)
- **ceph-replica-space**: Ceph replication network (MTU 9000)
- **public-space**: Public API endpoints (MTU 9000)
- **provider-space**: Provider network for external access (MTU 9000)

## Contributing

Network Doctor is designed to help with Canonical/Juju network diagnostics. Contributions are welcome for:

- Additional network issue detection patterns
- Better output formatting
- Support for additional network spaces
- Performance improvements

## License

This tool is provided as-is for network diagnostics and troubleshooting purposes.

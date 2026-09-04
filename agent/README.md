# Tally Sync Agent (On-Premise)

A standalone Python daemon designed to run on the local machine or network alongside **TallyPrime**.

## Overview
- Communicates with TallyPrime locally via Tally's XML Gateway (HTTP port 9000).
- Makes **outbound-only HTTPS requests** to Odoo 19 controllers (`/tally/agent/*`), requiring zero incoming open ports on the client network.
- Handles automated discovery of open Tally companies, AlterID delta polling, and execution of outbound Odoo-to-Tally queues.

## Quick Start

```bash
# Python 3.10+; no third-party packages are required.
python3 tally_agent.py --odoo-url "https://your-odoo.odoo.com" --token "YOUR_INSTANCE_AGENT_TOKEN" --interval 30
```

## Running as a Background Service
Can be registered as a Windows Service (via NSSM) or Linux systemd unit.

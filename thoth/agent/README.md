# Agent Module

XMTP-based agent for querying the Thoth message database via chat.

## Overview

This module provides a conversational interface to search and query scraped messages. Users can send messages via XMTP and receive search results.

## Files

### runner.py

Main agent runner that:
- Connects to XMTP network
- Listens for incoming messages
- Parses queries
- Returns search results

### __init__.py, __main__.py

Package initialization and entry point.

## Running

```bash
python -m thoth.agent
```

## Configuration

The agent uses credentials configured via environment variables or config file. See the main project README for XMTP setup.

## Query Examples

Once running, you can message the agent with queries like:

```
search discord general hello
```

```
messages from @username
```

```
recent #channel-name
```

## Status

🚧 **Work in Progress**

The agent module is under development. Current TODO items:
- Wire in XMTP client credentials
- Add richer query grammar (channels, authors, date ranges)
- Implement response formatting

See `TODO.md` in the project root for the full roadmap.

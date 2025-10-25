#!/usr/bin/env python3
"""
Freshdesk MCP Connector - v7.1 Final Stable
Author: Nuri Muhammet Birlik
Description: MCP connector for Freshdesk – compatible with all plans (free & paid).
"""

import os
import requests
import logging
import time
from typing import Dict, List, Any
from fastmcp import FastMCP
from dotenv import load_dotenv
from functools import lru_cache

# -------------------------------------------------------
# Logging Setup
# -------------------------------------------------------
LOG_FILE = "freshdesk_mcp.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger("FreshdeskMCP")

# -------------------------------------------------------
# Load environment
# -------------------------------------------------------
load_dotenv()
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN", "").replace("https://", "").replace("http://", "").strip("/")
FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")

if not FRESHDESK_DOMAIN or not FRESHDESK_API_KEY:
    raise ValueError("❌ Missing FRESHDESK_DOMAIN or FRESHDESK_API_KEY in environment variables")

BASE_URL = f"https://{FRESHDESK_DOMAIN}/api/v2"

# -------------------------------------------------------
# Helper Functions
# -------------------------------------------------------
def safe_request(method: str, endpoint: str, **kwargs) -> Any:
    """Universal request handler with retry logic."""
    retries = 3
    for attempt in range(retries):
        try:
            url = f"{BASE_URL}/{endpoint}"
            r = requests.request(
                method,
                url,
                auth=(FRESHDESK_API_KEY, "X"),
                timeout=20,
                **kwargs
            )
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt+1}/{retries} failed: {e}")
            time.sleep(2)
    return {"error": f"Max retries reached for {endpoint}"}


def fd_get(endpoint: str, params: dict = None) -> Any:
    """GET request with cache that supports dict params (fix for unhashable dict)."""
    frozen_params = frozenset(params.items()) if params else None
    return safe_request("GET", endpoint, params=dict(frozen_params) if frozen_params else None)


def fd_post(endpoint: str, data: dict) -> Any:
    """POST request."""
    return safe_request("POST", endpoint, json=data)


def fd_put(endpoint: str, data: dict) -> Any:
    """PUT request."""
    return safe_request("PUT", endpoint, json=data)

# -------------------------------------------------------
# Initialize MCP Server
# -------------------------------------------------------
server = FastMCP(
    name="Freshdesk MCP Connector",
    instructions="Access, search, and manage Freshdesk tickets via MCP tools."
)

# -------------------------------------------------------
# Tool: Overview
# -------------------------------------------------------
@server.tool(description="Get account overview including agents and groups")
async def overview() -> Dict[str, Any]:
    """Get basic Freshdesk account info."""
    company = {"domain": FRESHDESK_DOMAIN}
    agents = fd_get("agents")
    groups = fd_get("groups")
    return {"company": company, "agents": agents, "groups": groups}

# -------------------------------------------------------
# Tool: Search (universal for all plans)
# -------------------------------------------------------
@server.tool(description="Search tickets by keyword (works in all plans)")
async def search(query: str) -> Dict[str, Any]:
    """Search Freshdesk tickets by keyword in subject or description."""
    if not query.strip():
        return {"results": []}

    try:
        # 1️⃣ Try the search API first (only works on paid plans)
        data = fd_get("search/tickets", params={"query": f'"{query}"'})

        # 2️⃣ Fallback to /tickets if search is restricted
        tickets = []
        if isinstance(data, dict) and "error" in data:
            logger.warning("Search endpoint unavailable, falling back to /tickets")
            tickets = fd_get("tickets")
        else:
            tickets = data.get("results", data)

        if not tickets:
            return {"results": []}

        results = []
        for t in tickets:
            subject = (t.get("subject") or "").lower()
            desc = (t.get("description_text") or t.get("description") or "").lower()
            if query.lower() in subject or query.lower() in desc:
                results.append({
                    "id": t.get("id"),
                    "subject": t.get("subject", "No Subject"),
                    "status": t.get("status"),
                    "priority": t.get("priority"),
                    "url": f"https://{FRESHDESK_DOMAIN}/a/tickets/{t.get('id')}"
                })

        return {"results": results}

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"error": str(e)}

# -------------------------------------------------------
# Tool: Fetch Ticket
# -------------------------------------------------------
@server.tool(description="Fetch detailed info about a specific ticket")
async def fetch(ticket_id: int) -> Dict[str, Any]:
    ticket = fd_get(f"tickets/{ticket_id}")
    if "error" in ticket:
        return ticket

    conversations = fd_get(f"tickets/{ticket_id}/conversations")
    if isinstance(conversations, dict) and "error" in conversations:
        conversations = []

    return {
        "id": ticket.get("id"),
        "subject": ticket.get("subject"),
        "description": ticket.get("description_text"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "type": ticket.get("type"),
        "created_at": ticket.get("created_at"),
        "updated_at": ticket.get("updated_at"),
        "conversations": conversations,
        "url": f"https://{FRESHDESK_DOMAIN}/a/tickets/{ticket_id}"
    }

# -------------------------------------------------------
# Tool: Create Ticket
# -------------------------------------------------------
@server.tool(description="Create a new Freshdesk ticket")
async def create_ticket(email: str, subject: str, description: str, priority: int = 1, status: int = 2):
    """Create new ticket."""
    data = {
        "email": email,
        "subject": subject,
        "description": description,
        "priority": priority,
        "status": status
    }
    return fd_post("tickets", data)

# -------------------------------------------------------
# Tool: Update Ticket
# -------------------------------------------------------
@server.tool(description="Update ticket status, priority, or description")
async def update_ticket(ticket_id: int, status: int = None, priority: int = None, description: str = None):
    data = {}
    if status is not None:
        data["status"] = status
    if priority is not None:
        data["priority"] = priority
    if description:
        data["description"] = description
    return fd_put(f"tickets/{ticket_id}", data)

# -------------------------------------------------------
# Tool: Reply
# -------------------------------------------------------
@server.tool(description="Reply or add a private note to a ticket")
async def reply(ticket_id: int, body: str, private: bool = False):
    """Reply to a ticket."""
    data = {"body": body, "private": private}
    return fd_post(f"tickets/{ticket_id}/reply", data)

# -------------------------------------------------------
# Tool: Close Ticket
# -------------------------------------------------------
@server.tool(description="Close a ticket (set status = 5)")
async def close_ticket(ticket_id: int):
    """Close ticket."""
    return fd_put(f"tickets/{ticket_id}", {"status": 5})

# -------------------------------------------------------
# Tool: Health Check
# -------------------------------------------------------
@server.tool(description="Ping the connector to verify it's running")
async def ping() -> Dict[str, str]:
    """Simple health check."""
    return {"status": "ok", "domain": FRESHDESK_DOMAIN}

# -------------------------------------------------------
# Run Server
# -------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Starting Freshdesk MCP Connector on http://localhost:8001")
    print("🌐 MCP Discovery: http://localhost:8001/.well-known/mcp")
    print("🟢 SSE Handshake: /sse/")
    print("=" * 60)
    server.run(transport="sse", host="0.0.0.0", port=8001)


#!/usr/bin/env python3
"""
Freshdesk MCP Connector - Full Version
Author: Nuri Muhammet Birlik
Version: 6.3
"""

import os
import requests
import logging
from typing import Dict, List, Any
from fastmcp import FastMCP
from dotenv import load_dotenv

# -------------------------------------------------------
# Logging Setup
# -------------------------------------------------------
LOG_FILE = "freshdesk_mcp.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("FreshdeskMCP")

# -------------------------------------------------------
# Load .env
# -------------------------------------------------------
load_dotenv()
FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")  # e.g. yourcompany.freshdesk.com
FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")

if not FRESHDESK_DOMAIN or not FRESHDESK_API_KEY:
    raise ValueError("❌ Missing FRESHDESK_DOMAIN or FRESHDESK_API_KEY in .env file")

BASE_URL = f"https://{FRESHDESK_DOMAIN}/api/v2"

# -------------------------------------------------------
# Helper Functions
# -------------------------------------------------------
def fd_get(endpoint: str, params: dict = None) -> Any:
    """Generic GET request for Freshdesk API."""
    try:
        r = requests.get(
            f"{BASE_URL}/{endpoint}",
            params=params,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP {r.status_code}: {r.text}")
        return {"error": f"HTTP {r.status_code}: {r.text}"}
    except Exception as e:
        logger.error(str(e))
        return {"error": str(e)}


def fd_post(endpoint: str, data: dict) -> Any:
    """Generic POST request."""
    try:
        r = requests.post(
            f"{BASE_URL}/{endpoint}",
            json=data,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"POST {endpoint} failed: {e}")
        return {"error": str(e)}


def fd_put(endpoint: str, data: dict) -> Any:
    """Generic PUT request."""
    try:
        r = requests.put(
            f"{BASE_URL}/{endpoint}",
            json=data,
            auth=(FRESHDESK_API_KEY, "X"),
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"PUT {endpoint} failed: {e}")
        return {"error": str(e)}

# -------------------------------------------------------
# Pagination Helper
# -------------------------------------------------------
def paginate_tickets(query: str = None, per_page: int = 50, max_pages: int = 5) -> List[Dict[str, Any]]:
    """Handle Freshdesk search pagination."""
    all_tickets = []
    page = 1

    while page <= max_pages:
        params = {"page": page, "per_page": per_page}
        if query:
            params["query"] = f'"{query}"'
        data = fd_get("search/tickets", params=params)
        if "error" in data:
            break
        tickets = data.get("results", [])
        if not tickets:
            break
        all_tickets.extend(tickets)
        if len(tickets) < per_page:
            break
        page += 1

    return all_tickets

# -------------------------------------------------------
# Initialize MCP Server
# -------------------------------------------------------
server = FastMCP(
    name="Freshdesk MCP Connector",
    instructions="Access and search Freshdesk tickets and conversations via MCP tools."
)

# -------------------------------------------------------
# Tool: Overview
# -------------------------------------------------------
@server.tool()
async def overview() -> Dict[str, Any]:
    """Get basic information about the Freshdesk account."""
    company = {"domain": FRESHDESK_DOMAIN}
    agents = fd_get("agents")
    groups = fd_get("groups")
    return {"company": company, "agents": agents, "groups": groups}

# -------------------------------------------------------
# Tool: Search Tickets
# -------------------------------------------------------
@server.tool()
async def search(query: str) -> Dict[str, Any]:
    """Search Freshdesk tickets by keyword."""
    if not query.strip():
        return {"results": []}

    tickets = paginate_tickets(query)
    results = [{
        "id": t.get("id"),
        "subject": t.get("subject"),
        "description": (t.get("description_text", "")[:200] + "..."),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "url": f"https://{FRESHDESK_DOMAIN}/a/tickets/{t.get('id')}"
    } for t in tickets]

    return {"results": results}

# -------------------------------------------------------
# Tool: Fetch Ticket Details
# -------------------------------------------------------
@server.tool()
async def fetch(ticket_id: int) -> Dict[str, Any]:
    """Retrieve full details of a Freshdesk ticket."""
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
        "requester_id": ticket.get("requester_id"),
        "responder_id": ticket.get("responder_id"),
        "group_id": ticket.get("group_id"),
        "tags": ticket.get("tags", []),
        "conversations": [{
            "id": c.get("id"),
            "body_text": c.get("body_text", ""),
            "from_email": c.get("from_email"),
            "to_emails": c.get("to_emails"),
            "incoming": c.get("incoming"),
            "created_at": c.get("created_at")
        } for c in conversations],
        "metadata": {
            "source": "freshdesk",
            "url": f"https://{FRESHDESK_DOMAIN}/a/tickets/{ticket_id}"
        }
    }

# -------------------------------------------------------
# Tool: Create Ticket
# -------------------------------------------------------
@server.tool()
async def create_ticket(email: str, subject: str, description: str, priority: int = 1, status: int = 2) -> Dict[str, Any]:
    """Create a new Freshdesk ticket."""
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
@server.tool()
async def update_ticket(ticket_id: int, status: int = None, priority: int = None, description: str = None) -> Dict[str, Any]:
    """Update ticket fields."""
    data = {}
    if status is not None: data["status"] = status
    if priority is not None: data["priority"] = priority
    if description: data["description"] = description
    return fd_put(f"tickets/{ticket_id}", data)

# -------------------------------------------------------
# Tool: Reply to Ticket
# -------------------------------------------------------
@server.tool()
async def reply(ticket_id: int, body: str, private: bool = False) -> Dict[str, Any]:
    """Reply or add a private note to a ticket."""
    data = {"body": body, "private": private}
    return fd_post(f"tickets/{ticket_id}/reply", data)

# -------------------------------------------------------
# Tool: Close Ticket
# -------------------------------------------------------
@server.tool()
async def close_ticket(ticket_id: int) -> Dict[str, Any]:
    """Close a ticket (status = 5)."""
    return fd_put(f"tickets/{ticket_id}", {"status": 5})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Starting Freshdesk MCP server on http://localhost:8001")
    print("🌐 MCP Discovery: http://localhost:8001/.well-known/mcp")
    print("🟢 SSE Handshake: /sse/")
    print("\n🔧 Registered Tools:")

    try:
        loaded_tools = getattr(server, "_tools", getattr(server, "registry", {}))
        if loaded_tools:
            for tool_name, tool_data in loaded_tools.items():
                desc = getattr(tool_data, "description", "No description")
                print(f"   🛠️  {tool_name} → {desc}")
                logger.info(f"Tool loaded: {tool_name}")
            print(f"\n✅ Total Tools Loaded: {len(loaded_tools)}")
        else:
            print("⚠️ No tools found. Check @server.tool() decorators.")
    except Exception as e:
        print(f"❌ Error listing tools: {e}")
        logger.error(f"Error listing tools: {e}")

    print("=" * 60)
    server.run(transport="sse", host="0.0.0.0", port=8001)

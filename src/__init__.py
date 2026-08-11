# conductor/__init__.py
# LucidDreamer.AI — Conductor Package
# ZeroClaw Engineering Build 4

"""
The Conductor — the routing layer for LucidDreamer.AI.

'The conductor isn't a model. It isn't a backend. It isn't the room.
 The conductor is the routing layer.' — Lucineer
"""

from conductor.conductor import Conductor, RoutingDecision
from conductor.agent_pool import (
    AgentProfile,
    AgentTier,
    AgentAvailability,
    AGENT_POOL,
    BARNACLE,
    FLASH,
    PRO,
    HERMES,
    WESLEY,
    SEED,
    NEMOTRON,
    get_agent,
    get_available_agents,
    get_agents_for_intent,
)
from conductor.session import (
    VisitorProfile,
    VisitorIntent,
    SessionState,
    SessionPhase,
    SessionStore,
    IntentAnalyzer,
    EngagementTracker,
    RecruitmentStrategy,
    AgentSessionState,
    MessageRecord,
)

__version__ = "0.1.0"
__all__ = [
    # Conductor
    "Conductor",
    "RoutingDecision",
    # Agents
    "AgentProfile",
    "AgentTier",
    "AgentAvailability",
    "AGENT_POOL",
    "BARNACLE",
    "FLASH",
    "PRO",
    "HERMES",
    "WESLEY",
    "SEED",
    "NEMOTRON",
    "get_agent",
    "get_available_agents",
    "get_agents_for_intent",
    # Session
    "VisitorProfile",
    "VisitorIntent",
    "SessionState",
    "SessionPhase",
    "SessionStore",
    "IntentAnalyzer",
    "EngagementTracker",
    "RecruitmentStrategy",
    "AgentSessionState",
    "MessageRecord",
]

# Conductor package entry point — re-exports from internal modules
# This allows: from conductor import Conductor, VisitorProfile

import sys
import os

# Ensure src is on the path when running from the repo
_src = os.path.join(os.path.dirname(__file__), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# Re-export everything from the internal conductor package
from conductor import (
    Conductor,
    RoutingDecision,
    AgentProfile,
    AgentTier,
    AgentAvailability,
    AGENT_POOL,
    get_agent,
    get_available_agents,
    get_agents_for_intent,
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

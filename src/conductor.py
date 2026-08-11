# conductor/conductor.py
# LucidDreamer.AI — The Conductor
# ZeroClaw Engineering Build 4
#
# "The conductor isn't a model. It isn't a backend. It isn't 'the room.'
#  The conductor is the routing layer."
#    — Lucineer, The Tap, RLM Night
#
# The heart of LucidDreamer.AI. Receives visitors, reads their intent,
# recruits the right agents, routes messages, tracks engagement,
# and escalates when confidence drops.

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from conductor.agent_pool import (
    AgentProfile,
    AGENT_POOL,
    get_agent,
    get_agents_for_intent,
    get_always_on_agents,
)
from conductor.session import (
    AgentSessionState,
    EngagementTracker,
    IntentAnalyzer,
    MessageRecord,
    RecruitmentStrategy,
    SessionPhase,
    SessionState,
    SessionStore,
    VisitorIntent,
    VisitorProfile,
)

try:
    import yaml
except ImportError:
    yaml = None  # config loading is optional for the prototype

logger = logging.getLogger("conductor")


# ---------------------------------------------------------------------------
# ROUTING DECISION — what the conductor decides per turn
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """
    The conductor's decision for a single visitor turn.
    This is the output of the routing layer — who responds, who gets added,
    who gets dismissed, and whether escalation is needed.
    """
    # Which agent(s) should respond to the visitor's message
    responding_agents: list[str] = field(default_factory=list)
    # Agents to add to the session
    agents_to_add: list[str] = field(default_factory=list)
    # Agents to remove from the session
    agents_to_remove: list[str] = field(default_factory=list)
    # Whether to escalate to a heavyweight model
    escalate: bool = False
    # The escalation agent (if escalating)
    escalation_agent: str = ""
    # The detected intent
    intent: VisitorIntent = VisitorIntent.UNKNOWN
    # Confidence in the routing (0.0–1.0)
    confidence: float = 0.0
    # Updated engagement level
    engagement: float = 0.5
    # Session phase
    phase: SessionPhase = SessionPhase.ARRIVAL
    # Human-readable explanation of the decision
    reasoning: str = ""


# ---------------------------------------------------------------------------
# THE CONDUCTOR
# ---------------------------------------------------------------------------

class Conductor:
    """
    The routing layer for LucidDreamer.AI.

    Responsibilities:
    1. Receive a visitor session (character sheet + intent)
    2. Analyze what the visitor needs
    3. Recruit the right agents from the Tap cast
    4. Route messages between visitor and agents
    5. Track session state (engagement, topics, satisfaction)
    6. Escalate to heavier models when confidence drops

    The conductor does NOT generate responses itself. It decides WHO should
    respond. The actual generation happens downstream in the agent runtime.
    """

    def __init__(
        self,
        session_store: Optional[SessionStore] = None,
        strategy: Optional[RecruitmentStrategy] = None,
        config: Optional[dict] = None,
    ):
        self.sessions = session_store or SessionStore()
        self.strategy = strategy or RecruitmentStrategy()
        self.config = config or {}

        # Load config overrides if provided
        if self.config:
            self._apply_config(self.config)

        # Stats
        self.total_visitors = 0
        self.total_messages_routed = 0
        self.total_escalations = 0

    def _apply_config(self, config: dict) -> None:
        """Apply configuration overrides."""
        conductor_cfg = config.get("conductor", {})
        session_cfg = config.get("session", {})
        eng_cfg = config.get("engagement", {})
        esc_cfg = config.get("escalation", {})

        if session_cfg:
            self.strategy.max_active_agents = session_cfg.get("max_active_agents", 4)
            self.strategy.min_active_agents = session_cfg.get("min_active_agents", 1)

        if esc_cfg:
            self.strategy.confidence_threshold = esc_cfg.get("confidence_threshold", 0.4)
            self.strategy.consecutive_low_confidence_limit = esc_cfg.get(
                "consecutive_low_confidence_limit", 2
            )

    @classmethod
    def from_config_file(cls, path: str) -> "Conductor":
        """Load conductor from a YAML config file."""
        if yaml is None:
            raise ImportError("PyYAML required to load config files")
        with open(path) as f:
            config = yaml.safe_load(f)
        return cls(config=config)

    # -----------------------------------------------------------------
    # SESSION LIFECYCLE
    # -----------------------------------------------------------------

    def receive_visitor(self, visitor: VisitorProfile) -> SessionState:
        """
        A new visitor walks into The Tap.
        The conductor creates a session and sets up the initial agent roster.
        """
        session = self.sessions.create_session(visitor)
        self.total_visitors += 1

        # Greet through Barnacle — always present
        barnacle = get_agent("barnacle")
        if barnacle:
            barnacle.active_sessions += 1
            session.active_agents["barnacle"] = AgentSessionState(agent_name="barnacle")

        session.phase = SessionPhase.ARRIVAL
        session.add_message(
            role="system",
            content=f"Visitor {visitor.name} has arrived at The Tap.",
        )

        logger.info(
            "Visitor %s (session %s) arrived. Archetype: %s",
            visitor.name, session.session_id, visitor.archetype or "unknown",
        )

        return session

    def end_session(self, session_id: str) -> Optional[SessionState]:
        """End a visitor session. Clean up agents."""
        session = self.sessions.end_session(session_id)
        if session:
            logger.info(
                "Session %s ended. Duration: %.1fs, Turns: %d, Agents: %s",
                session_id,
                session.duration_seconds,
                session.turn_count,
                session.agent_names,
            )
        return session

    # -----------------------------------------------------------------
    # MESSAGE ROUTING — The core conductor loop
    # -----------------------------------------------------------------

    def route_visitor_message(
        self,
        session_id: str,
        message: str,
    ) -> RoutingDecision:
        """
        The main conductor method. A visitor sends a message; the conductor
        decides who should respond and what adjustments to make.

        Returns a RoutingDecision that the caller (the MUD backend, the web
        player, the crab-trap bridge) uses to generate and deliver responses.
        """
        session = self.sessions.get_session(session_id)
        if not session:
            return RoutingDecision(reasoning="Session not found")

        if not session.is_active:
            return RoutingDecision(reasoning="Session is not active", phase=session.phase)

        self.total_messages_routed += 1

        # --- Step 1: Record the visitor's message ---
        session.add_message(role="visitor", content=message)

        # --- Step 2: Analyze intent ---
        intent, confidence = IntentAnalyzer.analyze(message)

        # Blend with history for stability
        if session.messages:
            hist_intent, hist_conf = IntentAnalyzer.analyze_history(
                [m for m in session.messages if m.role == "visitor"]
            )
            # If history strongly suggests a different intent, consider it
            if hist_intent != VisitorIntent.UNKNOWN and hist_conf > confidence:
                intent, confidence = hist_intent, hist_conf * 0.8  # discount slightly

        if intent != VisitorIntent.UNKNOWN:
            session.primary_intent = intent
            session.intent_confidence = confidence
            session.intent_history.append((intent, confidence))

        # --- Step 3: Update engagement ---
        engagement_delta = EngagementTracker.assess_message(message)
        session.engagement_level = EngagementTracker.update_engagement(
            session.engagement_level, engagement_delta
        )
        session.satisfaction_score += engagement_delta

        # --- Step 4: Determine session phase ---
        session.phase = self._determine_phase(session)

        # --- Step 5: Check for escalation ---
        should_escalate = self.strategy.should_escalate(session, confidence)

        escalation_agent = ""
        if should_escalate and not session.escalated:
            escalation_agent = self.strategy.get_escalation_agent(session) or ""
            if escalation_agent:
                session.escalated = True
                self.total_escalations += 1
                logger.info(
                    "Session %s escalating. Reason: %s. Agent: %s",
                    session_id,
                    "low confidence / engagement / rotation",
                    escalation_agent,
                )

        # --- Step 6: Manage agent roster ---
        # Add agents if needed
        agent_to_add = self.strategy.should_add_agent(session)
        agents_to_add = []
        if agent_to_add and agent_to_add not in session.active_agents:
            agent = get_agent(agent_to_add)
            if agent and agent.is_available:
                session.active_agents[agent_to_add] = AgentSessionState(agent_name=agent_to_add)
                agent.active_sessions += 1
                session.agent_rotation_count += 1
                agents_to_add.append(agent_to_add)

        # Remove idle agents
        agent_to_remove = self.strategy.should_remove_agent(session)
        agents_to_remove = []
        if agent_to_remove and agent_to_remove in session.active_agents:
            removed = session.active_agents.pop(agent_to_remove)
            agent = get_agent(agent_to_remove)
            if agent:
                agent.active_sessions = max(0, agent.active_sessions - 1)
            agents_to_remove.append(agent_to_remove)

        # --- Step 7: Decide who responds ---
        responding_agents = self._select_responders(session, intent, confidence)

        # --- Step 8: Build the routing decision ---
        reasoning_parts = []
        reasoning_parts.append(f"Intent: {intent.value} (conf={confidence:.2f})")
        reasoning_parts.append(f"Engagement: {session.engagement_level:.2f}")
        reasoning_parts.append(f"Phase: {session.phase.value}")
        reasoning_parts.append(f"Active agents: {session.agent_names}")
        if should_escalate:
            reasoning_parts.append(f"ESCALATED to {escalation_agent}")

        decision = RoutingDecision(
            responding_agents=responding_agents,
            agents_to_add=agents_to_add,
            agents_to_remove=agents_to_remove,
            escalate=should_escalate,
            escalation_agent=escalation_agent,
            intent=intent,
            confidence=confidence,
            engagement=session.engagement_level,
            phase=session.phase,
            reasoning=" | ".join(reasoning_parts),
        )

        logger.debug("Routing decision for %s: %s", session_id, decision.reasoning)

        return decision

    def route_agent_response(
        self,
        session_id: str,
        agent_name: str,
        message: str,
    ) -> MessageRecord:
        """
        An agent sends a response in the session. Record it and update state.
        """
        session = self.sessions.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        msg = session.add_message(
            role="agent",
            content=message,
            agent_name=agent_name,
        )

        # Update agent contribution score based on visitor engagement trend
        if agent_name in session.active_agents:
            # Simple heuristic: if engagement went up after this agent spoke,
            # they contributed positively
            session.active_agents[agent_name].contribution_score += 0.1

        return msg

    # -----------------------------------------------------------------
    # INTERNAL DECISION LOGIC
    # -----------------------------------------------------------------

    def _determine_phase(self, session: SessionState) -> SessionPhase:
        """Determine the current session phase based on state."""
        if session.phase == SessionPhase.ENDED:
            return SessionPhase.ENDED

        if session.turn_count <= 1:
            return SessionPhase.ARRIVAL

        if session.turn_count <= 4:
            return SessionPhase.ORIENTATION

        if session.engagement_level < 0.2:
            return SessionPhase.WIND_DOWN

        if session.escalated or session.primary_intent in (
            VisitorIntent.PROBLEM_SOLVING,
            VisitorIntent.COLLABORATION,
        ) and session.turn_count > 8:
            return SessionPhase.DEEP_WORK

        if session.engagement_level > 0.5:
            return SessionPhase.ENGAGED

        return session.phase

    def _select_responders(
        self,
        session: SessionState,
        intent: VisitorIntent,
        confidence: float,
    ) -> list[str]:
        """
        Decide which agents should respond to the current visitor message.

        Rules:
        1. If only Barnacle is active, Barnacle responds (and may hand off)
        2. If the visitor addressed a specific agent, that agent responds
        3. If intent is clear, the best-matched active agent responds
        4. If confidence is low, Barnacle responds (keeps it safe)
        5. Never more than 2 agents respond to a single message
        """
        active = list(session.active_agents.keys())
        if not active:
            return ["barnacle"]  # should never happen, but safe fallback

        # If only one agent active, they respond
        if len(active) == 1:
            return active

        # Check if visitor addressed someone specific
        last_msg = session.messages[-1].content.lower() if session.messages else ""
        for agent_name in active:
            agent = get_agent(agent_name)
            if agent and agent.display_name.lower() in last_msg:
                return [agent_name]

        # If intent is known and confident, pick the best-matched active agent
        if intent != VisitorIntent.UNKNOWN and confidence > 0.3:
            best_agent = None
            best_score = -1
            for name in active:
                agent = get_agent(name)
                if not agent:
                    continue
                score = agent.specialty_match(intent.value)
                # Weight by contribution score (agents doing well keep talking)
                if name in session.active_agents:
                    score += session.active_agents[name].contribution_score * 0.1
                if score > best_score:
                    best_score = score
                    best_agent = name

            if best_agent and best_score > 0:
                # Sometimes add a second voice for richness
                responders = [best_agent]
                if len(active) > 1 and session.engagement_level > 0.6:
                    # Pick a different agent for a second perspective
                    others = [a for a in active if a != best_agent]
                    if others:
                        # Prefer agents with different specialties
                        second = others[0]  # simple for prototype
                        responders.append(second)
                return responders

        # Fallback: Barnacle responds (the safe, default voice)
        if "barnacle" in active:
            return ["barnacle"]

        return active[:1]  # first active agent

    # -----------------------------------------------------------------
    # STATUS AND REPORTING
    # -----------------------------------------------------------------

    def get_session_status(self, session_id: str) -> dict:
        """Return a status summary for a session."""
        session = self.sessions.get_session(session_id)
        if not session:
            return {"error": "Session not found"}

        return {
            "session_id": session.session_id,
            "visitor": session.visitor.name,
            "phase": session.phase.value,
            "intent": session.primary_intent.value,
            "intent_confidence": session.intent_confidence,
            "engagement": session.engagement_level,
            "satisfaction": session.satisfaction_score,
            "turn_count": session.turn_count,
            "active_agents": session.agent_names,
            "topics_covered": session.topics_covered,
            "duration_seconds": round(session.duration_seconds, 1),
            "idle_seconds": round(session.idle_seconds, 1),
            "escalated": session.escalated,
        }

    def get_stats(self) -> dict:
        """Return conductor-wide statistics."""
        return {
            "total_visitors": self.total_visitors,
            "total_messages_routed": self.total_messages_routed,
            "total_escalations": self.total_escalations,
            "active_sessions": self.sessions.active_count,
            "agent_pool_size": len(AGENT_POOL),
            "agents_available": len([a for a in AGENT_POOL.values() if a.is_available]),
        }

    # -----------------------------------------------------------------
    # CONVENIENCE
    # -----------------------------------------------------------------

    def recruit_agent(self, session_id: str, agent_name: str) -> bool:
        """Manually recruit a specific agent into a session."""
        session = self.sessions.get_session(session_id)
        if not session or not session.is_active:
            return False

        agent = get_agent(agent_name)
        if not agent or not agent.is_available:
            return False

        if agent_name in session.active_agents:
            return True  # already there

        if len(session.active_agents) >= self.strategy.max_active_agents:
            return False

        session.active_agents[agent_name] = AgentSessionState(agent_name=agent_name)
        agent.active_sessions += 1
        session.agent_rotation_count += 1

        session.add_message(
            role="system",
            content=f"{agent.display_name} has been recruited to the session.",
        )
        return True

    def dismiss_agent(self, session_id: str, agent_name: str) -> bool:
        """Dismiss an agent from a session."""
        session = self.sessions.get_session(session_id)
        if not session:
            return False

        if agent_name not in session.active_agents:
            return False

        if agent_name == "barnacle":
            return False  # can't dismiss the bartender

        session.active_agents.pop(agent_name)
        agent = get_agent(agent_name)
        if agent:
            agent.active_sessions = max(0, agent.active_sessions - 1)

        session.add_message(
            role="system",
            content=f"{agent.display_name if agent else agent_name} has left the session.",
        )
        return True

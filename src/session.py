# conductor/session.py
# LucidDreamer.AI — Session Management
# ZeroClaw Engineering Build 4
#
# "The conductor is the routing layer." — Lucineer
#
# SessionStore: per-visitor state
# Intent analysis from visitor messages
# Agent recruitment logic
# Escalation thresholds

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from conductor.agent_pool import (
    AgentProfile,
    AGENT_POOL,
    get_agent,
    get_agents_for_intent,
    get_always_on_agents,
    get_lightweight_agents,
    get_heavyweight_agents,
)


# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------

class VisitorIntent(str, Enum):
    """What the visitor wants from the session."""
    CONVERSATION = "conversation"
    CREATIVE = "creative"
    LEARNING = "learning"
    LISTENING = "listening"
    PROBLEM_SOLVING = "problem_solving"
    COLLABORATION = "collaboration"
    EXPLORATION = "exploration"
    UNKNOWN = "unknown"


class SessionPhase(str, Enum):
    """Where the visitor is in their session lifecycle."""
    ARRIVAL = "arrival"        # just walked in, Barnacle greets
    ORIENTATION = "orientation" # figuring out what they want
    ENGAGED = "engaged"        # actively interacting with agents
    DEEP_WORK = "deep_work"    # heavy collaboration or problem-solving
    WIND_DOWN = "wind_down"    # session naturally ending
    ENDED = "ended"            # session closed


@dataclass
class VisitorProfile:
    """
    A visitor to LucidDreamer.AI — the session prompt made flesh.
    The conductor reads this to decide who to summon.
    """
    visitor_id: str
    name: str = "Visitor"
    archetype: str = ""           # e.g., "curious explorer", "builder"
    personality_summary: str = "" # one-sentence description
    known_interests: list[str] = field(default_factory=list)

    # Session-level preferences
    preferred_pace: str = "medium"  # slow, medium, fast
    prefers_deep: bool = False      # wants heavy analysis over light chat


@dataclass
class MessageRecord:
    """A single message in the session."""
    role: str               # "visitor", "agent", "conductor", "system"
    content: str
    agent_name: str = ""    # which agent spoke (if role == "agent")
    timestamp: float = field(default_factory=time.time)
    intent_detected: str = ""
    confidence: float = 1.0


@dataclass
class AgentSessionState:
    """Tracks an agent's participation in a specific session."""
    agent_name: str
    recruited_at: float = field(default_factory=time.time)
    messages_sent: int = 0
    last_active: float = field(default_factory=time.time)
    contribution_score: float = 0.0  # how useful this agent has been


@dataclass
class SessionState:
    """
    The full state of a visitor session.
    This is the conductor's working memory for one visitor.
    """
    session_id: str
    visitor: VisitorProfile
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # Phase and intent
    phase: SessionPhase = SessionPhase.ARRIVAL
    primary_intent: VisitorIntent = VisitorIntent.UNKNOWN
    intent_confidence: float = 0.0
    intent_history: list[tuple[VisitorIntent, float]] = field(default_factory=list)

    # Agent management
    active_agents: dict[str, AgentSessionState] = field(default_factory=dict)
    agent_rotation_count: int = 0  # how many times agents have been swapped

    # Engagement tracking
    engagement_level: float = 0.5
    satisfaction_score: float = 0.0
    turn_count: int = 0
    consecutive_low_confidence: int = 0
    escalated: bool = False

    # Conversation
    messages: list[MessageRecord] = field(default_factory=list)

    # Topics covered (for tracking breadth)
    topics_covered: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.phase != SessionPhase.ENDED

    @property
    def duration_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def agent_names(self) -> list[str]:
        return list(self.active_agents.keys())

    def add_message(
        self,
        role: str,
        content: str,
        agent_name: str = "",
        intent_detected: str = "",
        confidence: float = 1.0,
    ) -> MessageRecord:
        """Record a message and update session state."""
        msg = MessageRecord(
            role=role,
            content=content,
            agent_name=agent_name,
            intent_detected=intent_detected,
            confidence=confidence,
        )
        self.messages.append(msg)
        self.last_activity = time.time()
        self.turn_count += 1

        if agent_name and agent_name in self.active_agents:
            self.active_agents[agent_name].messages_sent += 1
            self.active_agents[agent_name].last_active = time.time()

        return msg

    def mark_topic_covered(self, topic: str) -> None:
        """Track that a topic has been discussed."""
        if topic not in self.topics_covered:
            self.topics_covered.append(topic)


# ---------------------------------------------------------------------------
# INTENT ANALYSIS
# ---------------------------------------------------------------------------

class IntentAnalyzer:
    """
    Lightweight intent classifier that reads visitor messages and determines
    what kind of interaction they're looking for.

    This is deliberately keyword-based for the prototype — fast, free, no API
    calls. In production, this would be augmented with embedding-based
    classification and possibly a small fine-tuned model.
    """

    # Keyword maps — mirrors config.yaml but hardcoded for speed
    KEYWORDS: dict[VisitorIntent, list[str]] = {
        VisitorIntent.CONVERSATION: [
            "hello", "hey", "how are you", "what's up", "tell me about yourself",
            "hi ", "good morning", "good evening", "howdy", "chat",
        ],
        VisitorIntent.CREATIVE: [
            "write", "create", "story", "poem", "draw", "design", "build",
            "compose", "make", "invent", "imagine", "song", "art",
        ],
        VisitorIntent.LEARNING: [
            "how does", "why is", "what is", "explain", "teach", "learn",
            "understand", "show me how", "tutorial", "guide", "education",
        ],
        VisitorIntent.LISTENING: [
            "tell me a story", "play something", "read to me", "i'm bored",
            "entertain", "perform", "broadcast", "radio", "listen",
        ],
        VisitorIntent.PROBLEM_SOLVING: [
            "fix", "debug", "solve", "issue", "problem", "error", "broken",
            "help me", "stuck", "doesn't work", "crash", "fail",
        ],
        VisitorIntent.COLLABORATION: [
            "let's", "together", "collaborate", "help me make", "brainstorm",
            "co-create", "pair", "work with", "join", "team",
        ],
        VisitorIntent.EXPLORATION: [
            "show me", "what's here", "browse", "explore", "what can you do",
            "look around", "tour", "navigate", "find", "search",
        ],
    }

    @classmethod
    def analyze(cls, text: str) -> tuple[VisitorIntent, float]:
        """
        Classify visitor intent from a message.
        Returns (intent, confidence) where confidence is 0.0–1.0.
        """
        if not text or not text.strip():
            return VisitorIntent.UNKNOWN, 0.0

        text_lower = text.lower().strip()

        scores: dict[VisitorIntent, float] = {}

        for intent, keywords in cls.KEYWORDS.items():
            score = 0.0
            for kw in keywords:
                if kw in text_lower:
                    # Longer keyword matches are stronger signals
                    score += len(kw) / 10.0
            scores[intent] = score

        if not scores or max(scores.values()) == 0:
            return VisitorIntent.UNKNOWN, 0.0

        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]
        total_score = sum(scores.values())

        # Confidence: how dominant is the best intent?
        if total_score > 0:
            confidence = best_score / total_score
        else:
            confidence = 0.0

        # Boost confidence for exclamation marks and question marks
        # (stronger intent signals)
        if "!" in text:
            confidence = min(1.0, confidence + 0.1)
        if "?" in text and best_intent in (VisitorIntent.LEARNING, VisitorIntent.EXPLORATION):
            confidence = min(1.0, confidence + 0.1)

        return best_intent, round(confidence, 3)

    @classmethod
    def analyze_history(cls, messages: list[MessageRecord]) -> tuple[VisitorIntent, float]:
        """
        Determine dominant intent across a message history.
        More recent messages carry more weight.
        """
        if not messages:
            return VisitorIntent.UNKNOWN, 0.0

        weighted_scores: dict[VisitorIntent, float] = {}
        total_weight = 0.0

        for i, msg in enumerate(messages):
            if msg.role != "visitor":
                continue
            weight = 1.0 + (i / len(messages))  # newer = heavier
            intent, conf = cls.analyze(msg.content)
            if intent != VisitorIntent.UNKNOWN:
                weighted_scores[intent] = weighted_scores.get(intent, 0.0) + weight * conf
                total_weight += weight

        if not weighted_scores or total_weight == 0:
            return VisitorIntent.UNKNOWN, 0.0

        best_intent = max(weighted_scores, key=weighted_scores.get)
        confidence = min(1.0, weighted_scores[best_intent] / total_weight)

        return best_intent, round(confidence, 3)


# ---------------------------------------------------------------------------
# ENGAGEMENT TRACKER
# ---------------------------------------------------------------------------

class EngagementTracker:
    """
    Tracks how engaged a visitor is based on message signals.
    Used by the conductor to decide when to step up, step back, or wind down.
    """

    POSITIVE_SIGNALS = {
        "thanks", "that's great", "love it", "amazing", "interesting",
        "tell me more", "wow", "cool", "nice", "awesome", "great",
        "yes", "exactly", "perfect", "love", "good",
    }
    NEGATIVE_SIGNALS = {
        "boring", "that's wrong", "don't like", "stop", "bye",
        "ugh", "not helpful", "no", "bad", "terrible", "hate",
        "whatever", "waste of time", "meh",
    }

    @classmethod
    def assess_message(cls, text: str) -> float:
        """
        Returns an engagement delta for the message.
        Positive = visitor is engaged, negative = disengaging.
        """
        if not text or not text.strip():
            return -0.15  # silence is a negative signal

        text_lower = text.lower().strip()
        delta = 0.0

        # Check for positive/negative signals
        for signal in cls.POSITIVE_SIGNALS:
            if signal in text_lower:
                delta += 0.1
                break  # one positive signal per message

        for signal in cls.NEGATIVE_SIGNALS:
            if signal in text_lower:
                delta -= 0.15
                break  # one negative signal per message

        # Length is a signal — longer messages = more engaged
        word_count = len(text_lower.split())
        if word_count > 20:
            delta += 0.05
        elif word_count > 5:
            delta += 0.02
        elif word_count <= 2 and delta == 0.0:
            delta -= 0.05  # very short, neutral messages = slight decay

        # Questions show engagement
        if "?" in text:
            delta += 0.03

        return round(delta, 3)

    @classmethod
    def update_engagement(cls, current: float, message_delta: float) -> float:
        """Apply natural decay + message delta, clamped to [0, 1]."""
        decay = 0.02  # natural decay per turn
        new_level = current - decay + message_delta
        return max(0.0, min(1.0, round(new_level, 3)))


# ---------------------------------------------------------------------------
# AGENT RECRUITMENT
# ---------------------------------------------------------------------------

class RecruitmentStrategy:
    """
    Decides which agents to recruit for a given session state.
    The conductor's hiring department.
    """

    def __init__(
        self,
        max_active_agents: int = 4,
        min_active_agents: int = 1,
        confidence_threshold: float = 0.4,
        consecutive_low_confidence_limit: int = 2,
    ):
        self.max_active_agents = max_active_agents
        self.min_active_agents = min_active_agents
        self.confidence_threshold = confidence_threshold
        self.consecutive_low_confidence_limit = consecutive_low_confidence_limit

    def initial_roster(self, intent: VisitorIntent, confidence: float) -> list[str]:
        """
        Build the initial agent roster for a new session.
        Always includes Barnacle (the greeter) plus agents matched to intent.
        """
        roster: list[str] = []

        # Barnacle is always present — the greeter
        roster.append("barnacle")

        if intent == VisitorIntent.UNKNOWN or confidence < self.confidence_threshold:
            # Low confidence — keep it simple, just Barnacle
            return roster

        # Add primary agents for the intent
        agents = get_agents_for_intent(intent.value, include_secondary=False)
        for agent in agents:
            if len(roster) >= self.max_active_agents:
                break
            if agent.name not in roster and agent.is_available:
                roster.append(agent.name)

        return roster

    def should_escalate(
        self,
        session: SessionState,
        intent_confidence: float,
    ) -> bool:
        """
        Determine if the session needs escalation — bringing in a heavier model.
        Escalation triggers:
        1. Consecutive low-confidence intent readings
        2. Engagement dropping below threshold
        3. Agent rotation count getting high (nothing sticking)
        """
        # Check consecutive low confidence
        if intent_confidence < self.confidence_threshold:
            session.consecutive_low_confidence += 1
        else:
            session.consecutive_low_confidence = 0

        if session.consecutive_low_confidence >= self.consecutive_low_confidence_limit:
            return True

        # Engagement in the basement
        if session.engagement_level < 0.2:
            return True

        # Too much rotation — nothing is working
        if session.agent_rotation_count > 5:
            return True

        return False

    def get_escalation_agent(self, session: SessionState) -> Optional[str]:
        """
        Pick a heavyweight agent for escalation.
        Prefer Pro for general escalation, Nemotron for systems problems.
        """
        active = set(session.active_agents.keys())

        # If we don't have Pro and it's a general issue, bring in Pro
        if "pro" not in active:
            pro = get_agent("pro")
            if pro and pro.is_available:
                return "pro"

        # If it looks like a systems problem, get Nemotron
        if session.primary_intent == VisitorIntent.PROBLEM_SOLVING and "nemotron" not in active:
            nemotron = get_agent("nemotron")
            if nemotron and nemotron.is_available:
                return "nemotron"

        # If both heavy agents are already in and it's still not working,
        # bring in Hermes as a catalyst
        if "hermes" not in active:
            hermes = get_agent("hermes")
            if hermes and hermes.is_available:
                return "hermes"

        return None

    def should_add_agent(self, session: SessionState) -> Optional[str]:
        """
        Check if we should add a new agent to the roster.
        Returns agent name to add, or None.
        """
        if len(session.active_agents) >= self.max_active_agents:
            return None

        # If the intent has shifted and we don't have a matching agent
        if session.primary_intent != VisitorIntent.UNKNOWN:
            matched = get_agents_for_intent(session.primary_intent.value, include_secondary=False)
            active = set(session.active_agents.keys())
            for agent in matched:
                if agent.name not in active and agent.is_available:
                    return agent.name

        return None

    def should_remove_agent(self, session: SessionState) -> Optional[str]:
        """
        Check if we should remove an agent from the roster.
        Agents that have been quiet for a while get dismissed.
        Returns agent name to remove, or None.
        """
        now = time.time()
        # Never remove Barnacle
        for name, state in session.active_agents.items():
            if name == "barnacle":
                continue
            idle = now - state.last_active
            if idle > 120 and state.messages_sent < 2:  # 2 min idle, barely spoke
                return name
        return None


# ---------------------------------------------------------------------------
# SESSION STORE
# ---------------------------------------------------------------------------

class SessionStore:
    """
    Manages all active visitor sessions.
    In production, this would be backed by Durable Objects or D1.
    For the prototype, it's in-memory.
    """

    def __init__(self, max_sessions: int = 1000):
        self.sessions: dict[str, SessionState] = {}
        self.max_sessions = max_sessions

    def create_session(self, visitor: VisitorProfile) -> SessionState:
        """Create a new visitor session."""
        if len(self.sessions) >= self.max_sessions:
            self._evict_oldest_idle()

        session_id = str(uuid.uuid4())
        session = SessionState(session_id=session_id, visitor=visitor)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Retrieve a session by ID."""
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> Optional[SessionState]:
        """End and remove a session."""
        session = self.sessions.pop(session_id, None)
        if session:
            session.phase = SessionPhase.ENDED
            # Decrement agent session counts
            for agent_name in session.active_agents:
                agent = get_agent(agent_name)
                if agent:
                    agent.active_sessions = max(0, agent.active_sessions - 1)
        return session

    def get_active_sessions(self) -> list[SessionState]:
        """Return all currently active sessions."""
        return [s for s in self.sessions.values() if s.is_active]

    def cleanup_idle(self, timeout_seconds: int = 1800) -> list[str]:
        """Remove sessions that have been idle for too long. Returns removed IDs."""
        now = time.time()
        removed = []
        for sid, session in list(self.sessions.items()):
            if now - session.last_activity > timeout_seconds:
                self.end_session(sid)
                removed.append(sid)
        return removed

    def _evict_oldest_idle(self) -> None:
        """Remove the oldest idle session to make room."""
        if not self.sessions:
            return
        oldest_sid = min(
            self.sessions,
            key=lambda sid: self.sessions[sid].last_activity,
        )
        self.end_session(oldest_sid)

    @property
    def active_count(self) -> int:
        return len(self.get_active_sessions())

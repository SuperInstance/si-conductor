# conductor/tests/test_conductor.py
# ZeroClaw Engineering Build 4 — Conductor Tests
#
# "iron sharpens iron"

import pytest
import sys
import os

# Ensure parent dir on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from conductor.agent_pool import (
    AGENT_POOL,
    BARNACLE,
    FLASH,
    PRO,
    HERMES,
    WESLEY,
    SEED,
    NEMOTRON,
    AgentTier,
    AgentAvailability,
    get_agent,
    get_agents_for_intent,
    get_available_agents,
    get_always_on_agents,
    get_lightweight_agents,
    get_heavyweight_agents,
    reset_all_sessions,
)
from conductor.session import (
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
from conductor.conductor import Conductor, RoutingDecision


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all agent session counts before each test."""
    reset_all_sessions()
    yield
    reset_all_sessions()


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def visitor():
    return VisitorProfile(
        visitor_id="v-test-001",
        name="Test Visitor",
        archetype="curious explorer",
        personality_summary="Wants to learn and create.",
    )


@pytest.fixture
def conductor():
    return Conductor()


@pytest.fixture
def session_with_visitor(conductor, visitor):
    return conductor.receive_visitor(visitor)


# ---------------------------------------------------------------------------
# TESTS 1-3: AGENT POOL
# ---------------------------------------------------------------------------

class TestAgentPool:
    """Verify the agent pool is correctly defined and queryable."""

    def test_all_seven_agents_present(self):
        """The Tap cast has exactly 7 agents defined."""
        assert len(AGENT_POOL) == 7
        names = set(AGENT_POOL.keys())
        assert names == {"barnacle", "flash", "pro", "hermes", "wesley", "seed", "nemotron"}

    def test_barnacle_is_always_on_and_light(self):
        """Barnacle — the greeter — is always available and cheap."""
        assert BARNACLE.is_always_on
        assert BARNACLE.tier == AgentTier.LIGHT
        assert BARNACLE.specialty_match("conversation") == 1.0
        assert BARNACLE.cost_per_call == 0.0

    def test_agent_specialty_matching(self):
        """Agents match their specialties correctly."""
        assert FLASH.specialty_match("creative") == 1.0
        assert FLASH.specialty_match("collaboration") == 1.0
        assert FLASH.specialty_match("conversation") == 0.5  # secondary
        assert FLASH.specialty_match("problem_solving") == 0.0

        assert PRO.specialty_match("problem_solving") == 1.0
        assert WESLEY.specialty_match("learning") == 1.0
        assert NEMOTRON.specialty_match("problem_solving") == 1.0
        assert HERMES.specialty_match("collaboration") == 1.0
        assert SEED.specialty_match("exploration") == 1.0

    def test_heavyweight_vs_lightweight(self):
        """Heavy and light tiers are correctly separated."""
        heavy = get_heavyweight_agents()
        light = get_lightweight_agents()
        heavy_names = {a.name for a in heavy}
        light_names = {a.name for a in light}
        assert heavy_names == {"pro", "hermes", "nemotron"}
        assert light_names == {"barnacle", "flash", "wesley", "seed"}

    def test_get_agents_for_intent(self):
        """Intent-to-agent mapping returns the right agents."""
        creative_agents = get_agents_for_intent("creative")
        names = [a.name for a in creative_agents]
        assert "flash" in names  # primary
        assert "wesley" in names  # primary
        assert "hermes" in names  # also primary for Hermes

        # Without secondary — only primary specialists
        creative_primary = get_agents_for_intent("creative", include_secondary=False)
        primary_names = [a.name for a in creative_primary]
        assert "flash" in primary_names
        assert "wesley" in primary_names
        # Hermes has creative as primary specialty, so it's included
        assert "hermes" in primary_names
        # Seed is NOT a creative specialist
        assert "seed" not in primary_names

    def test_agent_availability_tracking(self):
        """Agents track their concurrent session count."""
        assert FLASH.is_available
        FLASH.active_sessions = FLASH.max_concurrent_sessions
        assert not FLASH.is_available
        FLASH.active_sessions = 0
        assert FLASH.is_available


# ---------------------------------------------------------------------------
# TESTS 4-6: INTENT ANALYSIS
# ---------------------------------------------------------------------------

class TestIntentAnalyzer:
    """Verify the intent classifier reads visitor messages correctly."""

    def test_creative_intent_detected(self):
        """A message about writing triggers creative intent."""
        intent, confidence = IntentAnalyzer.analyze("I want to write a story about the ocean")
        assert intent == VisitorIntent.CREATIVE
        assert confidence > 0.3

    def test_learning_intent_detected(self):
        """A question triggers learning intent."""
        intent, confidence = IntentAnalyzer.analyze("Can you explain how neural networks work?")
        assert intent == VisitorIntent.LEARNING
        assert confidence > 0.3

    def test_problem_solving_intent_detected(self):
        """A bug report triggers problem-solving intent."""
        intent, confidence = IntentAnalyzer.analyze("My code is broken and I need to debug it")
        assert intent == VisitorIntent.PROBLEM_SOLVING
        assert confidence > 0.3

    def test_conversation_intent_detected(self):
        """A greeting triggers conversation intent."""
        intent, confidence = IntentAnalyzer.analyze("Hey, hello! How are you doing?")
        assert intent == VisitorIntent.CONVERSATION
        assert confidence > 0.3

    def test_collaboration_intent_detected(self):
        """A let's-build-together message triggers collaboration."""
        intent, confidence = IntentAnalyzer.analyze("Let's brainstorm together and make something")
        assert intent == VisitorIntent.COLLABORATION
        assert confidence > 0.3

    def test_empty_message_is_unknown(self):
        """Empty messages produce unknown intent with zero confidence."""
        intent, confidence = IntentAnalyzer.analyze("")
        assert intent == VisitorIntent.UNKNOWN
        assert confidence == 0.0

        intent2, confidence2 = IntentAnalyzer.analyze("   ")
        assert intent2 == VisitorIntent.UNKNOWN

    def test_intent_history_analysis(self):
        """Historical analysis weights recent messages more."""
        messages = [
            MessageRecord(role="visitor", content="hello"),
            MessageRecord(role="visitor", content="hello"),
            MessageRecord(role="visitor", content="I want to write a story"),
            MessageRecord(role="visitor", content="help me create a poem"),
        ]
        intent, conf = IntentAnalyzer.analyze_history(messages)
        # Creative should dominate the later (heavier) messages
        assert intent == VisitorIntent.CREATIVE


# ---------------------------------------------------------------------------
# TESTS 7-9: ENGAGEMENT TRACKING
# ---------------------------------------------------------------------------

class TestEngagementTracker:
    """Verify engagement rises and falls correctly."""

    def test_positive_signals_boost_engagement(self):
        """Positive words increase engagement."""
        delta = EngagementTracker.assess_message("That's amazing! Tell me more!")
        assert delta > 0

    def test_negative_signals_drop_engagement(self):
        """Negative words decrease engagement."""
        delta = EngagementTracker.assess_message("This is boring and not helpful")
        assert delta < 0

    def test_long_messages_signal_engagement(self):
        """Longer messages show the visitor is invested."""
        long_msg = "I was thinking about this idea where we build a radio station " * 3
        delta = EngagementTracker.assess_message(long_msg)
        assert delta > 0

    def test_silence_is_negative(self):
        """Empty/silent messages decay engagement."""
        delta = EngagementTracker.assess_message("")
        assert delta < 0

    def test_engagement_clamps_to_valid_range(self):
        """Engagement never goes below 0 or above 1."""
        assert EngagementTracker.update_engagement(0.01, -0.5) == 0.0
        assert EngagementTracker.update_engagement(0.99, 0.5) == 1.0

    def test_engagement_decays_over_time(self):
        """Even with a neutral message, engagement decays slightly."""
        delta = EngagementTracker.assess_message("ok")
        updated = EngagementTracker.update_engagement(0.5, delta)
        # "ok" is 2 words, neutral — should decay
        assert updated <= 0.5


# ---------------------------------------------------------------------------
# TESTS 10-12: CONDUCTOR ROUTING DECISIONS
# ---------------------------------------------------------------------------

class TestConductorRouting:
    """Verify the conductor makes the right routing decisions."""

    def test_visitor_arrival_creates_session_with_barnacle(self, conductor, visitor):
        """A new visitor gets a session with Barnacle as greeter."""
        session = conductor.receive_visitor(visitor)
        assert session.session_id is not None
        assert "barnacle" in session.active_agents
        assert session.phase == SessionPhase.ARRIVAL
        assert session.turn_count >= 1  # system arrival message

    def test_creative_message_routes_to_creative_agent(self, conductor, session_with_visitor):
        """A creative message recruits a creative agent."""
        session = session_with_visitor

        # First, Barnacle greets — send a creative message
        decision = conductor.route_visitor_message(
            session.session_id,
            "I want to write a story about a lighthouse",
        )

        assert decision.intent == VisitorIntent.CREATIVE
        assert decision.confidence > 0
        assert len(decision.responding_agents) >= 1

        # Flash should be recruited (creative specialist)
        # Either added or already being routed to
        assert (
            "flash" in decision.agents_to_add
            or "flash" in session.active_agents
            or "flash" in decision.responding_agents
        )

    def test_barnacle_always_responds_when_alone(self, conductor, session_with_visitor):
        """When only Barnacle is active, Barnacle responds."""
        session = session_with_visitor
        decision = conductor.route_visitor_message(
            session.session_id,
            "Hi there!",
        )
        assert "barnacle" in decision.responding_agents

    def test_session_not_found_returns_error(self, conductor):
        """Routing to a non-existent session returns a safe fallback."""
        decision = conductor.route_visitor_message("nonexistent", "hello")
        assert "Session not found" in decision.reasoning
        assert decision.responding_agents == []

    def test_end_session_cleans_up_agents(self, conductor, session_with_visitor):
        """Ending a session decrements agent counts."""
        session = session_with_visitor
        assert BARNACLE.active_sessions >= 1

        conductor.end_session(session.session_id)
        assert session.phase == SessionPhase.ENDED
        # Session removed from store
        assert conductor.sessions.get_session(session.session_id) is None


# ---------------------------------------------------------------------------
# TESTS 13-15: AGENT RECRUITMENT AND ESCALATION
# ---------------------------------------------------------------------------

class TestRecruitmentAndEscalation:
    """Verify agent recruitment and escalation logic."""

    def test_initial_roster_always_includes_barnacle(self):
        """The initial roster always includes Barnacle."""
        strategy = RecruitmentStrategy()
        roster = strategy.initial_roster(VisitorIntent.CREATIVE, 0.9)
        assert "barnacle" in roster

    def test_initial_roster_includes_specialist_for_confident_intent(self):
        """High-confidence intent recruits matching specialists."""
        strategy = RecruitmentStrategy()
        roster = strategy.initial_roster(VisitorIntent.PROBLEM_SOLVING, 0.9)
        assert "barnacle" in roster
        assert "pro" in roster or "nemotron" in roster

    def test_low_confidence_keeps_roster_minimal(self):
        """Low confidence intent keeps just Barnacle."""
        strategy = RecruitmentStrategy()
        roster = strategy.initial_roster(VisitorIntent.UNKNOWN, 0.1)
        assert roster == ["barnacle"]

    def test_escalation_triggers_on_low_confidence(self):
        """Consecutive low-confidence readings trigger escalation."""
        strategy = RecruitmentStrategy(
            confidence_threshold=0.4,
            consecutive_low_confidence_limit=2,
        )
        visitor = VisitorProfile(visitor_id="v1", name="Escalation Visitor")
        session = SessionState(session_id="s1", visitor=visitor)
        session.active_agents["barnacle"] = conductor_import_agent_state("barnacle")

        # First low-confidence reading
        assert not strategy.should_escalate(session, 0.2)
        # Second low-confidence reading
        assert strategy.should_escalate(session, 0.2)

    def test_escalation_picks_pro_first(self):
        """General escalation brings in Pro first."""
        strategy = RecruitmentStrategy()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = SessionState(session_id="s1", visitor=visitor)
        session.active_agents["barnacle"] = conductor_import_agent_state("barnacle")

        agent = strategy.get_escalation_agent(session)
        assert agent == "pro"

    def test_escalation_picks_nemotron_for_systems_problems(self):
        """Systems problems bring in Nemotron."""
        strategy = RecruitmentStrategy()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = SessionState(session_id="s1", visitor=visitor)
        session.primary_intent = VisitorIntent.PROBLEM_SOLVING
        session.active_agents["barnacle"] = conductor_import_agent_state("barnacle")
        session.active_agents["pro"] = conductor_import_agent_state("pro")

        agent = strategy.get_escalation_agent(session)
        assert agent == "nemotron"

    def test_engagement_freefall_triggers_escalation(self):
        """Engagement below 0.2 triggers escalation."""
        strategy = RecruitmentStrategy()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = SessionState(session_id="s1", visitor=visitor)
        session.engagement_level = 0.15

        assert strategy.should_escalate(session, 0.8)

    def test_conductor_escalation_in_routing(self, conductor, session_with_visitor):
        """Full conductor flow: repeated unclear messages trigger escalation."""
        session = session_with_visitor

        # Send several unclear messages to trigger escalation
        for _ in range(4):
            conductor.route_visitor_message(session.session_id, "asdf jkl")

        assert session.consecutive_low_confidence > 0
        # After enough low-confidence turns, should escalate
        assert session.escalated or session.engagement_level < 0.3


# ---------------------------------------------------------------------------
# TESTS 16-18: SESSION STORE AND LIFECYCLE
# ---------------------------------------------------------------------------

class TestSessionStore:
    """Verify session lifecycle management."""

    def test_create_and_retrieve_session(self):
        """Sessions can be created and retrieved."""
        store = SessionStore()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = store.create_session(visitor)
        assert store.get_session(session.session_id) is session

    def test_end_session_removes_from_store(self):
        """Ended sessions are removed."""
        store = SessionStore()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = store.create_session(visitor)
        store.end_session(session.session_id)
        assert store.get_session(session.session_id) is None

    def test_cleanup_idle_removes_old_sessions(self):
        """Idle sessions are cleaned up."""
        store = SessionStore()
        visitor = VisitorProfile(visitor_id="v1", name="Test")
        session = store.create_session(visitor)

        # Simulate old activity
        session.last_activity = 0  # epoch
        removed = store.cleanup_idle(timeout_seconds=100)
        assert session.session_id in removed
        assert store.get_session(session.session_id) is None

    def test_max_sessions_eviction(self):
        """Oldest idle session is evicted when max is reached."""
        store = SessionStore(max_sessions=2)
        v1 = store.create_session(VisitorProfile(visitor_id="v1", name="A"))
        v2 = store.create_session(VisitorProfile(visitor_id="v2", name="B"))
        v3 = store.create_session(VisitorProfile(visitor_id="v3", name="C"))

        # v1 should have been evicted (oldest)
        assert store.get_session(v1.session_id) is None
        assert store.get_session(v2.session_id) is not None
        assert store.get_session(v3.session_id) is not None

    def test_phase_progression(self, conductor, session_with_visitor):
        """Session progresses through phases as turns increase."""
        session = session_with_visitor
        assert session.phase == SessionPhase.ARRIVAL

        # Send a few messages to move past arrival
        for i in range(5):
            conductor.route_visitor_message(
                session.session_id,
                f"I want to write story number {i}",
            )

        assert session.phase in (SessionPhase.ORIENTATION, SessionPhase.ENGAGED, SessionPhase.DEEP_WORK)
        assert session.turn_count >= 5


# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------

def conductor_import_agent_state(name: str):
    """Helper to create an AgentSessionState for tests."""
    from conductor.session import AgentSessionState
    return AgentSessionState(agent_name=name)


# ---------------------------------------------------------------------------
# TESTS 19-20: CONDUCTOR STATS AND MANAGEMENT
# ---------------------------------------------------------------------------

class TestConductorManagement:
    """Verify conductor-level management functions."""

    def test_manual_recruit_and_dismiss(self, conductor, session_with_visitor):
        """The conductor can manually recruit and dismiss agents."""
        session = session_with_visitor

        # Recruit Flash
        assert conductor.recruit_agent(session.session_id, "flash")
        assert "flash" in session.active_agents

        # Can't dismiss Barnacle
        assert not conductor.dismiss_agent(session.session_id, "barnacle")

        # Can dismiss Flash
        assert conductor.dismiss_agent(session.session_id, "flash")
        assert "flash" not in session.active_agents

    def test_conductor_stats(self, conductor, visitor):
        """Stats track visitors, messages, and escalations."""
        session = conductor.receive_visitor(visitor)
        conductor.route_visitor_message(session.session_id, "Hello there!")

        stats = conductor.get_stats()
        assert stats["total_visitors"] == 1
        assert stats["total_messages_routed"] >= 1
        assert stats["agent_pool_size"] == 7

    def test_session_status_report(self, conductor, session_with_visitor):
        """Session status gives a useful summary."""
        session = session_with_visitor
        conductor.route_visitor_message(session.session_id, "I want to create something")

        status = conductor.get_session_status(session.session_id)
        assert status["visitor"] == "Test Visitor"
        assert status["turn_count"] >= 1
        assert "barnacle" in status["active_agents"]
        assert status["phase"] in ("arrival", "orientation", "engaged", "deep_work")

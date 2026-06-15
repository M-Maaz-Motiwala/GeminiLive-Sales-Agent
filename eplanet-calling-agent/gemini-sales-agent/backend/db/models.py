from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float,
    ForeignKey, Enum, JSON, func
)
import enum


class Base(AsyncAttrs, DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    admin = "admin"
    viewer = "viewer"


class AgentType(str, enum.Enum):
    sales = "sales"
    research = "research"
    code_analysis = "code_analysis"
    document_qa = "document_qa"
    lead_qualification = "lead_qualification"
    outbound_sales = "outbound_sales"
    summarization = "summarization"
    router = "router"


class SessionStatus(str, enum.Enum):
    active = "active"
    ended = "ended"
    error = "error"


class ChannelType(str, enum.Enum):
    web = "web"
    sip = "sip"
    outbound = "outbound"


class LeadStatus(str, enum.Enum):
    new = "new"
    qualified = "qualified"
    contacted = "contacted"
    closed = "closed"
    lost = "lost"


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    indexing = "indexing"
    indexed = "indexed"
    failed = "failed"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    running = "running"
    paused = "paused"
    completed = "completed"


class CampaignLeadStatus(str, enum.Enum):
    pending = "pending"
    dialing = "dialing"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class OutputType(str, enum.Enum):
    summary = "summary"
    lead_capture = "lead_capture"
    action_items = "action_items"
    call_disposition = "call_disposition"
    research_report = "research_report"
    code_analysis = "code_analysis"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.admin, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agents = relationship("Agent", back_populates="created_by")
    notes = relationship("Note", back_populates="created_by")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    type = Column(Enum(AgentType), default=AgentType.sales, nullable=False)
    system_prompt_template = Column(Text, nullable=False)
    inbound_prompt_template = Column(Text, nullable=True)
    outbound_prompt_template = Column(Text, nullable=True)
    voice = Column(String(100), default="Zephyr")
    model = Column(String(100), default="gemini-3.1-flash-live-preview")
    enabled_tools = Column(JSON, default=list)
    inbound_extension = Column(String(10), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User", back_populates="agents")
    personas = relationship("Persona", back_populates="agent", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="agent")
    documents = relationship("Document", back_populates="agent")


class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    traits = Column(JSON, default=dict)
    example_phrases = Column(JSON, default=list)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agent = relationship("Agent", back_populates="personas")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    caller_id = Column(String(255), nullable=True)
    channel_type = Column(Enum(ChannelType), default=ChannelType.web, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(SessionStatus), default=SessionStatus.active, nullable=False)
    summary = Column(Text, nullable=True)
    meta = Column(JSON, default=dict)

    agent = relationship("Agent", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="session", cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="source_session")
    outputs = relationship("Output", back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user | model
    text = Column(Text, nullable=False)
    has_audio = Column(Boolean, default=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="messages")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(255), nullable=False)
    parameters = Column(JSON, default=dict)
    result = Column(JSON, nullable=True)
    called_at = Column(DateTime(timezone=True), server_default=func.now())
    duration_ms = Column(Integer, nullable=True)

    session = relationship("Session", back_populates="tool_calls")


class DoNotCall(Base):
    __tablename__ = "dnc_list"

    id = Column(Integer, primary_key=True)
    phone_e164 = Column(String(20), unique=True, nullable=False, index=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    status = Column(Enum(CampaignStatus), default=CampaignStatus.draft, nullable=False)
    description = Column(Text, nullable=True)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    agent = relationship("Agent", backref="campaigns")
    campaign_leads = relationship(
        "CampaignLead", back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignLead(Base):
    __tablename__ = "campaign_leads"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    endpoint = Column(String(255), nullable=True)
    status = Column(
        Enum(CampaignLeadStatus), default=CampaignLeadStatus.pending, nullable=False
    )
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    last_error = Column(Text, nullable=True)
    dialed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("Campaign", back_populates="campaign_leads")
    lead = relationship("Lead")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    phone_e164 = Column(String(20), nullable=True, index=True)
    company = Column(String(255), nullable=True)
    status = Column(Enum(LeadStatus), default=LeadStatus.new, nullable=False)
    source_session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_session = relationship("Session", back_populates="leads")
    lead_notes = relationship("Note", primaryjoin="and_(Note.entity_type=='lead', foreign(Note.entity_id)==Lead.id)")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    company = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)  # session | lead | contact
    entity_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    created_by = relationship("User", back_populates="notes")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    name = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.pending, nullable=False)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    indexed_at = Column(DateTime(timezone=True), nullable=True)

    agent = relationship("Agent", back_populates="documents")


class Output(Base):
    __tablename__ = "outputs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    output_type = Column(Enum(OutputType), nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="outputs")

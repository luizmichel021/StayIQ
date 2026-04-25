from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone


Base = declarative_base()


class User(Base):

    __tablename__ = 'users'
    __table_args__ = {"schema": "stayiq"}

    id_user      = Column(Integer, primary_key=True)
    email        = Column(String, unique=True, nullable=False)
    name         = Column(String)
    phone_number = Column(String, nullable=True)
    token_enc    = Column(LargeBinary)

    created_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    default_alerts = Column(String, default="60min,30min,15min,5min")

    events       = relationship("Event", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User email={self.email}>"


class Event(Base):
    """
    Evento sincronizado do Google Calendar.
    Janela de sync: hoje → +7 dias.
    Todos os eventos são capturados (sem filtro de tipo).
    Para filtrar por palavra-chave, ajuste calendar_service.py:
        KEYWORD_FILTER = ['check', 'reserva', 'airbnb']
    """

    __tablename__ = 'events'
    __table_args__ = {"schema": "stayiq"}

    id              = Column(Integer, primary_key=True)
    user_email      = Column(String, ForeignKey("stayiq.users.email", ondelete="CASCADE"), nullable=False)
    google_event_id = Column(String, nullable=False)
    title           = Column(String, nullable=False)
    start_time      = Column(DateTime(timezone=True), nullable=False)
    end_time        = Column(DateTime(timezone=True), nullable=True)
    synced_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user    = relationship("User", back_populates="events")
    alerts  = relationship("ScheduledAlert", back_populates="event", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Event title={self.title} start={self.start_time}>"


class ScheduledAlert(Base):
    """
    Alerta agendado para um evento.
    Tipos possíveis: '60min', '30min', '15min', '5min'
    O scheduler cria 4 alertas por evento automaticamente.
    O usuário pode ligar/desligar cada um via dashboard (is_active).
    """

    __tablename__ = 'scheduled_alerts'
    __table_args__ = {"schema": "stayiq"}

    id             = Column(Integer, primary_key=True)
    user_email     = Column(String, nullable=False)
    event_id       = Column(Integer, ForeignKey("stayiq.events.id", ondelete="CASCADE"), nullable=False)
    alert_type     = Column(String, nullable=False)   # '60min' | '30min' | '15min' | '5min'
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    is_active      = Column(Boolean, default=True)
    sent           = Column(Boolean, default=False)
    sent_at        = Column(DateTime(timezone=True), nullable=True)

    event = relationship("Event", back_populates="alerts")

    def __repr__(self):
        return f"<Alert event_id={self.event_id} type={self.alert_type} active={self.is_active}>"

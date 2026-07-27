"""
models.py — Database tables: users, holdings, watchlist.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    holdings  = relationship("Holding", back_populates="user",
                             cascade="all, delete-orphan")
    watchlist = relationship("WatchlistItem", back_populates="user",
                             cascade="all, delete-orphan")


class Holding(Base):
    """A stock the user owns — enables the SELL/HOLD (position-aware) view later."""
    __tablename__ = "holdings"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker     = Column(String, nullable=False)
    shares     = Column(Float, nullable=False)
    avg_price  = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="holdings")


class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id      = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker  = Column(String, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "ticker", name="uq_user_ticker"),)

    user = relationship("User", back_populates="watchlist")


class Transaction(Base):
    """Immutable log of every buy/sell — enables transaction-history questions."""
    __tablename__ = "transactions"

    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    ticker    = Column(String, nullable=False)
    action    = Column(String, nullable=False)   # "BUY" or "SELL"
    shares    = Column(Float, nullable=False)
    price     = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

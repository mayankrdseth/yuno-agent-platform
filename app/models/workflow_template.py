from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from app.db.base import Base


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False)
    description = Column(String(300), nullable=True)
    agent_ids = Column(Text, nullable=False, default="[]")
    edges = Column(Text, nullable=False, default="[]")
    is_builtin = Column(Integer, default=0)  # 1 = pre-built template
    created_at = Column(DateTime, default=datetime.utcnow)

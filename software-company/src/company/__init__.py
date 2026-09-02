"""Software Company — event-driven multi-agent skeleton.

Modules:
  events     pydantic envelope + payload models, khớp topics/schemas
  bus        message bus có validate, partition theo key, in-memory (thay bằng Redis Streams/Kafka)
  blackboard shared-context có owner theo namespace
  registry   nạp agent prompt + skill từ thư mục agents/ và skills/
  supervisor watchdog + budget + knowledge
  gates      human gate với timeout
  graph      LangGraph wiring (tùy chọn, import lazily)
"""
__version__ = "0.1.0"

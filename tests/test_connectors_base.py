from agent.connectors import (
    Message,
    OutboundMessage,
    InboundEvent,
    OutboundEvent,
    Connector,
    OnMessage,
)


def test_message_defaults():
    m = Message(text="hello", sender="u1", sender_name="Alice")
    assert m.images == []


def test_outbound_message_defaults():
    m = OutboundMessage(text="hi")
    assert m.images == []


def test_inbound_event():
    msg = Message(text="hey", sender="u1", sender_name="Bob")
    ev = InboundEvent(channel="c1", message=msg, connector_name="telegram")
    assert ev.channel == "c1"
    assert ev.connector_name == "telegram"


def test_outbound_event():
    msg = OutboundMessage(text="reply")
    ev = OutboundEvent(channel="c1", to="u1", message=msg)
    assert ev.to == "u1"


def test_connector_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Connector()  # type: ignore[abstract]

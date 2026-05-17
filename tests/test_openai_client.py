import memory_system.openai_client as openai_client
from memory_system.openai_client import OpenAIChatClient


class FakeUsage:
    input_tokens = 1
    output_tokens = 2
    total_tokens = 3


class FakeResponse:
    output_text = '{"updated_memory":"# Core Memory\\n","updated_user":"# User Memory\\n","episodic_append":"## Snapshot"}'
    usage = FakeUsage()


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


class FakeOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.responses = FakeResponses()
        self.instances.append(self)


def test_openai_client_sets_timeout_retries_and_output_limit(monkeypatch):
    monkeypatch.setattr(openai_client, "OpenAI", FakeOpenAI)

    client = OpenAIChatClient(
        api_key="key",
        base_url="https://example.test",
        timeout=12,
        max_retries=3,
        max_output_tokens=456,
    )
    client.chat(model="gpt-5.4", messages=[{"role": "user", "content": "hi"}])
    client.compact_memory(model="gpt-5.4", prompt="compress")

    instance = FakeOpenAI.instances[0]
    assert instance.kwargs["timeout"] == 12
    assert instance.kwargs["max_retries"] == 3
    assert instance.responses.calls[0]["max_output_tokens"] == 456
    assert instance.responses.calls[1]["max_output_tokens"] == 456


def test_openai_client_requires_optional_dependency(monkeypatch):
    monkeypatch.setattr(openai_client, "OpenAI", None)

    try:
        OpenAIChatClient(api_key="key")
    except RuntimeError as exc:
        assert "memorywiki[openai]" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for missing optional OpenAI dependency")

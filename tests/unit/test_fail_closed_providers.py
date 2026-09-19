"""Unit tests verifying fail-closed behavior across all providers.
Verifies that unconfigured providers fail explicitly with typed errors and never fake success.
"""

import pytest
from packages.communications.base import OutboundMessageRequest
from packages.communications.gateway import EmailProvider
from packages.llm.providers import NIMProvider, OllamaProvider, ProviderNotConfiguredError
from packages.media.worker import VideoWorker
from packages.payments.base import CreateCheckoutRequest
from packages.payments.dodo import DodoPaymentsProvider, PaymentNotConfiguredError
from packages.shared.config import settings
from packages.shared.models import ChannelType


@pytest.mark.asyncio
async def test_dodo_provider_fails_closed_when_unconfigured():
    """Dodo provider must refuse checkout creation and status queries when api_key is missing."""
    provider = DodoPaymentsProvider()
    provider.api_key = None

    req = CreateCheckoutRequest(
        project_id="proj_fail_closed",
        client_id="client_01",
        quote_id="quote_01",
        amount=100.0,
        currency="USD",
        product_name="Service",
        customer_email="test@example.com",
    )

    with pytest.raises(PaymentNotConfiguredError) as exc_info:
        await provider.create_checkout(req)
    assert "not configured" in str(exc_info.value)

    with pytest.raises(PaymentNotConfiguredError) as exc_info:
        await provider.get_payment_status("pay_123")
    assert "not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_email_provider_fails_closed_when_unconfigured():
    """Email provider must return NOT_CONFIGURED when SMTP is disabled or unconfigured."""
    provider = EmailProvider()
    saved_enabled = settings.EMAIL_ENABLED
    settings.EMAIL_ENABLED = False

    try:
        req = OutboundMessageRequest(
            recipient="user@example.com",
            sender="agent@example.com",
            channel=ChannelType.EMAIL,
            content="Hello world",
        )
        res = await provider.send_message(req)
        assert res.success is False
        assert res.status == "NOT_CONFIGURED"
    finally:
        settings.EMAIL_ENABLED = saved_enabled


@pytest.mark.asyncio
async def test_llm_providers_fail_closed_when_unconfigured():
    """Ollama and NIM providers must raise ProviderNotConfiguredError when api_key is missing."""
    ollama = OllamaProvider()
    ollama.api_key = None

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        await ollama.generate(messages=[{"role": "user", "content": "Hello"}])
    assert "not configured" in str(exc_info.value)

    nim = NIMProvider()
    nim.api_key = None

    with pytest.raises(ProviderNotConfiguredError) as exc_info:
        await nim.generate(messages=[{"role": "user", "content": "Hello"}])
    assert "not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_video_worker_fails_closed_without_ffprobe(monkeypatch):
    """VideoWorker must raise FileNotFoundError if ffprobe executable is missing on PATH."""
    worker = VideoWorker()
    monkeypatch.setattr("shutil.which", lambda bin_name: None)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        tf.write(b"fake media content")
        tf_path = tf.name

    with pytest.raises(FileNotFoundError) as exc_info:
        await worker.probe_media(tf_path)
    assert "ffprobe" in str(exc_info.value)

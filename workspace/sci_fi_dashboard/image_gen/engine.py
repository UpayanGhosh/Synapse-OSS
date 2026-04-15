"""engine.py — ImageGenEngine: unified image generation dispatcher.

Routes generate() calls to the configured provider (openai or fal).
All errors are caught and logged — generate() always returns bytes or None.
"""

import logging

from synapse_config import SynapseConfig

_logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 4000


class ImageGenEngine:
    """Dispatch image generation requests to the configured provider.

    Reads provider, size, quality, and enabled settings from
    ``SynapseConfig.load().image_gen`` at construction time.

    Usage::

        engine = ImageGenEngine()
        png_bytes = await engine.generate("A sunset over mountains")
    """

    def __init__(self) -> None:
        self._cfg = SynapseConfig.load()
        self._img_cfg: dict = self._cfg.image_gen

    async def generate(self, prompt: str) -> bytes | None:
        """Generate an image for *prompt* and return raw image bytes.

        Returns ``None`` (with a logged error) when:
        - The configured provider API key is missing.
        - The provider call raises any exception.
        - An unknown provider is specified.

        Args:
            prompt: Text description of the image to generate.
                    Silently truncated to MAX_PROMPT_CHARS (4000) if longer.

        Returns:
            Raw PNG/image bytes on success, or ``None`` on failure.
        """
        # Truncate silently — never raise on length
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS]

        provider = self._img_cfg.get("provider", "openai")

        try:
            if provider == "openai":
                return await self._generate_openai(prompt)
            elif provider == "fal":
                return await self._generate_fal(prompt)
            else:
                _logger.error(
                    "ImageGenEngine: unknown provider %r — expected 'openai' or 'fal'", provider
                )
                return None
        except Exception:
            _logger.exception("ImageGenEngine.generate() failed for provider %r", provider)
            return None

    async def _generate_openai(self, prompt: str) -> bytes | None:
        """Dispatch to the OpenAI gpt-image-1 provider."""
        api_key = self._cfg.providers.get("openai", {}).get("api_key", "")
        if not api_key:
            _logger.error(
                "ImageGenEngine: OpenAI api_key is missing from providers.openai — "
                "set it in synapse.json providers.openai.api_key"
            )
            return None

        from sci_fi_dashboard.image_gen.providers.openai_img import generate_openai_image  # noqa

        size = self._img_cfg.get("size", "1024x1024")
        quality = self._img_cfg.get("quality", "medium")
        return await generate_openai_image(prompt, api_key=api_key, size=size, quality=quality)

    async def _generate_fal(self, prompt: str) -> bytes | None:
        """Dispatch to the fal.ai FLUX provider."""
        api_key = self._cfg.providers.get("fal", {}).get("api_key", "")
        if not api_key:
            _logger.error(
                "ImageGenEngine: fal api_key is missing from providers.fal — "
                "set it in synapse.json providers.fal.api_key"
            )
            return None

        from sci_fi_dashboard.image_gen.providers.fal_img import generate_fal_image  # noqa

        image_size = self._img_cfg.get("image_size", "square_hd")
        return await generate_fal_image(prompt, api_key=api_key, image_size=image_size)

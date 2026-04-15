"""openai_img.py — OpenAI gpt-image-1 image generation provider.

Uses gpt-image-1 which ALWAYS returns b64_json (never URL).
response_format parameter is not supported and must not be passed.
"""

import base64
import logging

_logger = logging.getLogger(__name__)


async def generate_openai_image(
    prompt: str,
    api_key: str,
    size: str = "1024x1024",
    quality: str = "medium",
) -> bytes:
    """Generate an image using OpenAI gpt-image-1 and return PNG bytes.

    Args:
        prompt:  The text prompt (caller is responsible for length truncation).
        api_key: OpenAI API key.
        size:    Image size string, e.g. "1024x1024", "1792x1024", "1024x1792".
        quality: Quality level — "low", "medium", or "high".

    Returns:
        Raw PNG bytes decoded from the b64_json response.

    Raises:
        Any exception from the openai SDK is propagated to the caller.
    """
    from openai import AsyncOpenAI  # lazy import — openai is optional dependency

    client = AsyncOpenAI(api_key=api_key)
    result = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
    )
    # gpt-image-1 always returns b64_json — never URL
    b64_data = result.data[0].b64_json
    return base64.b64decode(b64_data)

"""fal_img.py — fal.ai FLUX image generation provider.

Uses fal-ai/flux/dev model via fal-client SDK.
fal-client reads the API key from the FAL_KEY environment variable.
"""

import logging
import os

import httpx

_logger = logging.getLogger(__name__)


async def generate_fal_image(
    prompt: str,
    api_key: str,
    image_size: str = "square_hd",
) -> bytes:
    """Generate an image using fal.ai FLUX (fal-ai/flux/dev) and return image bytes.

    Args:
        prompt:     The text prompt (caller is responsible for length truncation).
        api_key:    fal.ai API key (written to FAL_KEY env var before the call).
        image_size: Size preset — "square_hd", "square", "portrait_4_3", etc.

    Returns:
        Raw image bytes downloaded from the fal.ai CDN URL.

    Raises:
        Any exception from fal_client or httpx is propagated to the caller.
    """
    import fal_client  # lazy import — fal-client is optional dependency

    # fal-client reads the key from the environment
    os.environ["FAL_KEY"] = api_key

    response = await fal_client.run_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "image_size": image_size,
            "num_images": 1,
        },
    )

    image_url = response["images"][0]["url"]
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        return resp.content

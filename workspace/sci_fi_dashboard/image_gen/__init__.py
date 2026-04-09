"""image_gen — Image generation engine for Synapse-OSS.

Provides ImageGenEngine with dual provider support:
- OpenAI gpt-image-1 (default)
- fal.ai FLUX (fal-ai/flux/dev)
"""

from sci_fi_dashboard.image_gen.engine import ImageGenEngine

__all__ = ["ImageGenEngine"]

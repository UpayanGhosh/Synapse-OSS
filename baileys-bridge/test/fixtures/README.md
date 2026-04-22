# Test Fixtures

## test_voice.ogg

Synthetic 1-second silence OGG Opus, 48kHz mono, 1 channel.

Generated on 2026-04-22 via a hand-crafted Node.js script that produces a
standards-compliant minimal OGG container:

- Page 0: BOS (beginning-of-stream) + OpusHead identification packet
- Page 1: OpusTags comment packet (vendor string "Synapse", zero user comments)
- Page 2: EOS (end-of-stream) + one silent Opus frame (DTX comfort-noise packet)

**Contains ZERO PII — safe for OSS commit.**

No `ffmpeg` required at test runtime. The file is committed directly to the repository
so media-shape tests (`send_shapes.test.js`) have a real OGG Opus binary to use as a
fixture without any runtime audio tooling dependency.

File size: ~129 bytes. First 4 bytes: `OggS` (OGG capture pattern).

### Why this approach

`node:test` (the test runner used by this bridge) has no built-in audio synthesis.
Rather than add a dev-dependency or require `ffmpeg`, the fixture is committed as a
known-good binary so:

1. CI environments without audio codecs can run media shape tests.
2. The OGG header is verifiable by inspection (`b.slice(0,4).toString() === 'OggS'`).
3. No personal audio content is included.

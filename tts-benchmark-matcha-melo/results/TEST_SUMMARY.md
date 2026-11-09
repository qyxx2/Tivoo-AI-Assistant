# Test summary

Same Mandarin utterance was synthesized by both models on the connected ARM64 device. Values below are from the warm (second) generation in each process.

| Model | Threads | Audio duration | Generation time | RTF | Output | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| Matcha Baker | 1 | 11.985 s | 2.985 s | 0.249 | 22.05 kHz | 248.5 MB |
| Matcha Baker | 2 | 12.010 s | 1.864 s | 0.155 | 22.05 kHz | 246.8 MB |
| Matcha Baker | 4 | 11.979 s | 1.309 s | 0.109 | 22.05 kHz | 248.3 MB |
| MeloTTS (full precision) | 1 | 11.047 s | 22.221 s | 2.012 | 44.1 kHz | 414.2 MB |
| MeloTTS (full precision) | 2 | 11.214 s | 13.122 s | 1.170 | 44.1 kHz | 414.9 MB |
| MeloTTS (full precision) | 4 | 11.233 s | 8.988 s | 0.800 | 44.1 kHz | 414.9 MB |

Recommended audition pair:
- results/matcha_t4_warm.wav
- results/melo_t4_warm.wav

RTF below 1 means speech is synthesized faster than its playback duration. Perceptual quality was not automatically scored.

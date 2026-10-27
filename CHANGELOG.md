# Changelog

All notable user-visible changes are documented here.

## [0.1.0] - Unreleased prerelease

### Added

- Source-only build and installation flow for the verified USA v1.00 disc.
- D3D12, Vulkan, and software rendering in one launcher-driven executable.
- 1x-8x internal rendering and optional xBRZ texture scaling.
- Optional D3D12 SMAA 1x High post-process anti-aliasing.
- Optional startup shortcut that completes memory-stick/title initialization
  and transitions directly to the main menu.
- Controller configuration, secure savedata loading/import, audio, media HLE,
  fullscreen presentation, and deterministic benchmark tooling.
- Public source checks that require no copyrighted game data.

### Known limitations

- This is not a full-game compatibility release.
- Secure save creation/reload, complete media coverage, full playthroughs, and
  long soak runs remain unvalidated.
- Some later scenes remain below the fixed-quality 60 FPS performance target.
- Builds require a user-supplied, SHA-1-verified ULUS-10077 v1.00 ISO and the
  exact `psp-recomp` revision pinned in `config/mga2.toml`.

[0.1.0]: https://github.com/Tzeentchnet/MetalGearAcid2-Recomp/releases/tag/v0.1.0

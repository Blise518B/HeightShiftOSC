# Changelog

All notable changes to HeightShiftOSC will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GPL v3 License - All code contributions must be open-sourced
- Startup Mode Selection (Query vs Load Fixed Height)
- Preserve Height on Avatar Switch feature
- Rapid Burst System for avatar change detection

### Changed
- Updated documentation structure and added comprehensive guides
- Documentation now includes all features: Startup Mode, Preserve Height on Avatar, Rapid Burst system, and mDNS Discovery

## [1.0.0] - 2025-01-XX

### Added
- Initial release of HeightShiftOSC
- Real-time height adjustment (1 cm - 100 m range)
- Quick-adjust buttons: ±1 cm, ±10 cm, ±100 cm
- Profile system with 4 saved height presets
- VRChat OSC connection via IP/Port configuration
- Window geometry persistence
- Dark-themed modern UI using CustomTkinter

### Features
- **mDNS Discovery**: Automatically discovers VRChat's OSC port via Zeroconf
- **Avatar Change Detection**: Preserves height when switching avatars in VRChat
- **Rapid Burst System**: Sends 20 OSC messages over 2 seconds after avatar swap to ensure height locks
- **Dynamic Port Assignment**: Uses random high ports for OSC receiver to avoid conflicts

### Technical Details
- Python 3.7+ with CustomTkinter for GUI
- python-osc library for OSC communication
- Zeroconf for mDNS service discovery
- Requests for HTTP queries to VRChat's OSCQuery endpoint

## Version History Notes

| Date | Version | Status |
|------|---------|--------|
| 2025-XX-XX | 1.0.0 | Initial Release |

---

**License**: This project is licensed under the GNU GPL v3 - see the LICENSE file for details.